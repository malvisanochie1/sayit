import asyncio
import os
import re
import threading
import uuid
from datetime import timedelta

import edge_tts
from flask import (
    Flask,
    Response,
    jsonify,
    render_template,
    request,
    send_from_directory,
    session,
)

import custom_voice

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", os.urandom(32))
app.permanent_session_lifetime = timedelta(days=365)
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024  # 10MB, plenty for a short voice sample

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

CUSTOM_VOICE_PREFIX = "custom:"

VOICE_GROUPS = {
    "US — Multilingual (most natural)": {
        "en-US-AndrewMultilingualNeural": "Andrew (Male)",
        "en-US-AvaMultilingualNeural": "Ava (Female)",
        "en-US-BrianMultilingualNeural": "Brian (Male)",
        "en-US-EmmaMultilingualNeural": "Emma (Female)",
    },
    "United States": {
        "en-US-AriaNeural": "Aria (Female)",
        "en-US-GuyNeural": "Guy (Male)",
        "en-US-JennyNeural": "Jenny (Female, Conversational)",
        "en-US-AndrewNeural": "Andrew (Male)",
        "en-US-AvaNeural": "Ava (Female)",
        "en-US-BrianNeural": "Brian (Male)",
        "en-US-EmmaNeural": "Emma (Female)",
        "en-US-ChristopherNeural": "Christopher (Male)",
        "en-US-EricNeural": "Eric (Male)",
        "en-US-RogerNeural": "Roger (Male)",
        "en-US-SteffanNeural": "Steffan (Male)",
        "en-US-MichelleNeural": "Michelle (Female)",
        "en-US-AnaNeural": "Ana (Female)",
    },
    "United Kingdom": {
        "en-GB-SoniaNeural": "Sonia (Female)",
        "en-GB-RyanNeural": "Ryan (Male)",
        "en-GB-LibbyNeural": "Libby (Female)",
        "en-GB-MaisieNeural": "Maisie (Female)",
        "en-GB-ThomasNeural": "Thomas (Male)",
    },
    "Ireland": {
        "en-IE-ConnorNeural": "Connor (Male)",
        "en-IE-EmilyNeural": "Emily (Female)",
    },
    "Canada": {
        "en-CA-ClaraNeural": "Clara (Female)",
        "en-CA-LiamNeural": "Liam (Male)",
    },
    "Australia": {
        "en-AU-NatashaNeural": "Natasha (Female)",
        "en-AU-WilliamMultilingualNeural": "William (Male, Multilingual)",
    },
    "India": {
        "en-IN-NeerjaNeural": "Neerja (Female)",
        "en-IN-NeerjaExpressiveNeural": "Neerja Expressive (Female)",
        "en-IN-PrabhatNeural": "Prabhat (Male)",
    },
    "New Zealand": {
        "en-NZ-MitchellNeural": "Mitchell (Male)",
        "en-NZ-MollyNeural": "Molly (Female)",
    },
    "South Africa": {
        "en-ZA-LeahNeural": "Leah (Female)",
        "en-ZA-LukeNeural": "Luke (Male)",
    },
    "Singapore": {
        "en-SG-LunaNeural": "Luna (Female)",
    },
    "Nigeria": {
        "en-NG-EzinneNeural": "Ezinne (Female)",
        "en-NG-AbeoNeural": "Abeo (Male)",
    },
}

VOICES = {
    voice_id: label
    for group in VOICE_GROUPS.values()
    for voice_id, label in group.items()
}

FILENAME_PATTERN = re.compile(r"^[a-f0-9]{32}\.mp3$")
VOICE_ID_PATTERN = re.compile(r"^[a-f0-9]{32}$")

# Rough estimate used only to drive the progress bar (not exact):
# edge-tts's neural voices produce audio at roughly 48kbps.
WORDS_PER_MINUTE = 140
ESTIMATED_BYTES_PER_SECOND = 6000

JOBS = {}
JOBS_LOCK = threading.Lock()


def _session_id() -> str:
    """Private per-browser id (signed cookie) that namespaces a person's
    custom voices in Cloudinary so no one else can see or use them."""
    if "cv_session" not in session:
        session["cv_session"] = uuid.uuid4().hex
        session.permanent = True
    return session["cv_session"]


def _estimate_total_bytes(text: str) -> int:
    word_count = max(len(text.split()), 1)
    estimated_seconds = (word_count / WORDS_PER_MINUTE) * 60
    return max(int(estimated_seconds * ESTIMATED_BYTES_PER_SECOND), 1)


async def _stream_generate(job: dict, text: str, voice: str, out_path: str) -> None:
    communicate = edge_tts.Communicate(text, voice)
    with open(out_path, "wb") as audio_file:
        async for chunk in communicate.stream():
            if job["cancel_event"].is_set():
                job["status"] = "cancelling"
                break
            if chunk["type"] == "audio":
                audio_file.write(chunk["data"])
                job["bytes_written"] += len(chunk["data"])


def _run_job(job_id: str, text: str, voice: str, out_path: str) -> None:
    job = JOBS[job_id]
    try:
        asyncio.run(_stream_generate(job, text, voice, out_path))
    except Exception as exc:
        job["status"] = "error"
        job["error"] = (
            "Couldn't reach the speech service. This tool needs an internet "
            "connection even though it's free — check your connection and try again."
        )
        _cleanup_file(out_path)
        return

    if job["cancel_event"].is_set():
        job["status"] = "cancelled"
        _cleanup_file(out_path)
    else:
        job["status"] = "done"
        job["audio_url"] = f"/audio/{os.path.basename(out_path)}"


def _run_custom_job(job_id: str, session_id: str, voice_id: str, text: str, out_path: str) -> None:
    job = JOBS[job_id]
    try:
        custom_voice.clone_speech(session_id, voice_id, text, job, out_path)
    except custom_voice.CustomVoiceError as exc:
        job["status"] = "error"
        job["error"] = str(exc)
        _cleanup_file(out_path)
        return
    except Exception:
        job["status"] = "error"
        job["error"] = "Voice cloning failed unexpectedly — please try again."
        _cleanup_file(out_path)
        return

    if job["status"] == "cancelling" or job["cancel_event"].is_set():
        job["status"] = "cancelled"
        _cleanup_file(out_path)
    elif job["status"] != "error":
        job["status"] = "done"
        job["audio_url"] = f"/audio/{os.path.basename(out_path)}"


def _cleanup_file(path: str) -> None:
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


@app.route("/")
def index():
    return render_template("index.html", voice_groups=VOICE_GROUPS)


@app.route("/synthesize", methods=["POST"])
def synthesize():
    text = (request.form.get("text") or "").strip()
    voice = request.form.get("voice") or ""

    if not text:
        return jsonify({"error": "Please enter some text first."}), 400

    is_custom = voice.startswith(CUSTOM_VOICE_PREFIX)
    if not is_custom and voice not in VOICES:
        return jsonify({"error": "Please choose a valid voice."}), 400

    job_id = uuid.uuid4().hex
    filename = f"{job_id}.mp3"
    out_path = os.path.join(OUTPUT_DIR, filename)

    if is_custom:
        voice_id = voice[len(CUSTOM_VOICE_PREFIX):]
        session_id = _session_id()
        estimated_total_bytes = custom_voice.estimate_total_bytes(text)
    else:
        estimated_total_bytes = _estimate_total_bytes(text)

    with JOBS_LOCK:
        JOBS[job_id] = {
            "status": "running",
            "bytes_written": 0,
            "estimated_total_bytes": estimated_total_bytes,
            "cancel_event": threading.Event(),
            "audio_url": None,
            "error": None,
        }

    if is_custom:
        thread = threading.Thread(
            target=_run_custom_job,
            args=(job_id, session_id, voice_id, text, out_path),
            daemon=True,
        )
    else:
        thread = threading.Thread(
            target=_run_job, args=(job_id, text, voice, out_path), daemon=True
        )
    thread.start()

    return jsonify({"job_id": job_id}), 202


@app.route("/status/<job_id>")
def status(job_id):
    job = JOBS.get(job_id)
    if job is None:
        return jsonify({"error": "Unknown job."}), 404

    progress = min(
        int((job["bytes_written"] / job["estimated_total_bytes"]) * 100), 99
    )
    if job["status"] == "done":
        progress = 100

    return jsonify(
        {
            "status": job["status"],
            "progress": progress,
            "audio_url": job["audio_url"],
            "error": job["error"],
        }
    )


@app.route("/cancel/<job_id>", methods=["POST"])
def cancel(job_id):
    job = JOBS.get(job_id)
    if job is None:
        return jsonify({"error": "Unknown job."}), 404

    if job["status"] == "running":
        job["cancel_event"].set()

    return jsonify({"ok": True})


@app.route("/custom-voice/list")
def custom_voice_list():
    try:
        voices = custom_voice.list_voices(_session_id())
    except custom_voice.CustomVoiceError as exc:
        return jsonify({"error": str(exc)}), 503
    return jsonify({"voices": voices})


@app.route("/custom-voice/add", methods=["POST"])
def custom_voice_add():
    name = (request.form.get("name") or "").strip()
    sample = request.files.get("sample")

    if not name:
        return jsonify({"error": "Please give this voice a name."}), 400
    if sample is None or sample.filename == "":
        return jsonify({"error": "Please provide a voice sample recording."}), 400

    voice_id = uuid.uuid4().hex
    try:
        record = custom_voice.add_voice(_session_id(), voice_id, name, sample)
    except custom_voice.CustomVoiceError as exc:
        return jsonify({"error": str(exc)}), 503
    except Exception:
        return jsonify({"error": "Couldn't save that voice sample — please try again."}), 500

    return jsonify({"voice": record}), 201


@app.route("/custom-voice/delete/<voice_id>", methods=["POST"])
def custom_voice_delete(voice_id):
    if not VOICE_ID_PATTERN.match(voice_id):
        return jsonify({"error": "Invalid voice id."}), 400

    try:
        deleted = custom_voice.delete_voice(_session_id(), voice_id)
    except custom_voice.CustomVoiceError as exc:
        return jsonify({"error": str(exc)}), 503

    if not deleted:
        return jsonify({"error": "Voice not found."}), 404
    return jsonify({"ok": True})


@app.route("/custom-voice/sample/<voice_id>")
def custom_voice_sample(voice_id):
    if not VOICE_ID_PATTERN.match(voice_id):
        return jsonify({"error": "Invalid voice id."}), 400

    try:
        result = custom_voice.get_sample_bytes(_session_id(), voice_id)
    except custom_voice.CustomVoiceError as exc:
        return jsonify({"error": str(exc)}), 503

    if result is None:
        return jsonify({"error": "Voice not found."}), 404

    audio_bytes, audio_format = result
    return Response(audio_bytes, mimetype=f"audio/{audio_format}")


@app.route("/audio/<filename>")
def audio(filename):
    if not FILENAME_PATTERN.match(filename):
        return jsonify({"error": "Invalid filename."}), 400
    return send_from_directory(OUTPUT_DIR, filename)


if __name__ == "__main__":
    # Local development only — Render starts the app via gunicorn (see Procfile),
    # which never executes this block, so production never runs in debug mode.
    debug_mode = os.environ.get("FLASK_DEBUG", "1") == "1"
    app.run(debug=debug_mode, port=5000, threaded=True)
