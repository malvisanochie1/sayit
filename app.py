import asyncio
import base64
import os
import re
import tempfile
import threading
import time
import uuid

import cloudinary
import cloudinary.uploader
import cloudinary.utils
import edge_tts
from flask import Flask, jsonify, render_template, request, send_from_directory
from gradio_client import Client

app = Flask(__name__)

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

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
OPENVOICE_SPACE_URL = "myshell-ai/OpenVoiceV2"
OPENVOICE_FN_INDEX = 1
OPENVOICE_STYLES = {
    "en_us": "English (US)",
    "en_default": "English (Default)",
    "en_br": "English (British)",
    "en_au": "English (Australian)",
    "en_in": "English (Indian)",
    "es_default": "Spanish",
    "fr_default": "French",
    "jp_default": "Japanese",
    "zh_default": "Chinese",
    "kr_default": "Korean",
}
CLONE_MAX_WORDS = 50
MAX_REFERENCE_AUDIO_BYTES = 25 * 1024 * 1024
ALLOWED_REFERENCE_AUDIO_EXTENSIONS = {
    ".aac",
    ".aif",
    ".aiff",
    ".caf",
    ".flac",
    ".m4a",
    ".mp3",
    ".mp4",
    ".ogg",
    ".wav",
    ".webm",
}
CLOUDINARY_CLOUD_NAME = "dtnv63qnw"
CLOUDINARY_API_KEY = "461935167362794"

# Rough estimate used only to drive the progress bar (not exact):
# edge-tts's neural voices produce audio at roughly 48kbps.
WORDS_PER_MINUTE = 140
ESTIMATED_BYTES_PER_SECOND = 6000

JOBS = {}
JOBS_LOCK = threading.Lock()
CLONE_JOBS = {}
CLONE_JOBS_LOCK = threading.Lock()


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


def _cleanup_file(path: str) -> None:
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


def _set_clone_job(job: dict, **updates) -> None:
    job.update(updates)


def _validate_clone_text(text: str):
    if not text:
        return "Please enter the text you want to hear in the cloned voice."
    if len(text.split()) > CLONE_MAX_WORDS:
        return (
            "Please keep cloned-voice text to 50 words or fewer. "
            "The public OpenVoice V2 demo rejects longer prompts."
        )
    return None


def _get_audio_extension(filename: str) -> str:
    return os.path.splitext(filename.lower())[1]


def _validate_reference_audio(audio_file):
    if audio_file is None or not audio_file.filename:
        return "Please upload a short voice sample first."

    extension = _get_audio_extension(audio_file.filename)
    if extension not in ALLOWED_REFERENCE_AUDIO_EXTENSIONS:
        return "Please upload a common audio file such as MP3, WAV, M4A, OGG, or WEBM."

    stream = audio_file.stream
    try:
        stream.seek(0, os.SEEK_END)
        size = stream.tell()
        stream.seek(0)
    except (OSError, AttributeError):
        size = 0

    if size > MAX_REFERENCE_AUDIO_BYTES:
        return "Please upload an audio sample smaller than 25 MB."

    return None


def _save_reference_audio(audio_file) -> str:
    extension = _get_audio_extension(audio_file.filename) or ".wav"
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=extension)
    temp_file.close()
    audio_file.save(temp_file.name)
    return temp_file.name


def _build_openvoice_client() -> Client:
    token = os.environ.get("HUGGINGFACE_TOKEN") or None
    return Client(
        OPENVOICE_SPACE_URL,
        token=token,
        verbose=False,
        httpx_kwargs={"timeout": 180},
    )


def _clean_space_message(message: str) -> str:
    cleaned = (message or "").strip()
    cleaned = cleaned.replace("[ERROR]", "").replace("[HTTP ERROR]", "").strip()
    return cleaned or "The voice model did not return audio."


def _write_base64_audio(data: str, suffix: str = ".wav") -> str:
    if "," in data:
        data = data.rsplit(",", 1)[1]
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    try:
        temp_file.write(base64.b64decode(data))
        return temp_file.name
    finally:
        temp_file.close()


def _audio_path_from_gradio_value(value):
    if not value:
        return None

    if isinstance(value, str):
        return value

    if isinstance(value, dict):
        for key in ("path", "name"):
            path = value.get(key)
            if path and os.path.exists(path):
                return path
        if value.get("data"):
            suffix = _get_audio_extension(value.get("orig_name") or "") or ".wav"
            return _write_base64_audio(value["data"], suffix)
        if value.get("url"):
            return value["url"]

    for attr in ("path", "name"):
        path = getattr(value, attr, None)
        if path and os.path.exists(path):
            return path

    data = getattr(value, "data", None)
    if data:
        orig_name = getattr(value, "orig_name", "") or ""
        suffix = _get_audio_extension(orig_name) or ".wav"
        return _write_base64_audio(data, suffix)

    url = getattr(value, "url", None)
    if url:
        return url

    return None


def _extract_cloned_audio_path(result):
    if isinstance(result, (list, tuple)):
        info = result[0] if len(result) > 0 else ""
        audio_value = result[1] if len(result) > 1 else None
    else:
        info = ""
        audio_value = result

    return _audio_path_from_gradio_value(audio_value), str(info or "")


def _call_openvoice_with_retry(job: dict, text: str, style: str, reference_path: str):
    last_error = None

    for attempt in range(2):
        if attempt:
            _set_clone_job(job, progress=35, message="Retrying the voice model...")
            time.sleep(2)
        else:
            _set_clone_job(job, progress=20, message="Waking the voice model...")

        try:
            client = _build_openvoice_client()
            _set_clone_job(
                job,
                progress=45,
                message="Cloning your voice... this can take up to a couple of minutes",
            )
            result = client.predict(
                text,
                style,
                reference_path,
                True,
                fn_index=OPENVOICE_FN_INDEX,
            )
            audio_path, info = _extract_cloned_audio_path(result)
            if not audio_path:
                raise RuntimeError(_clean_space_message(info))
            return audio_path, info
        except Exception as exc:
            last_error = exc

    raise RuntimeError(str(last_error) or "The voice model failed after retrying once.")


def _ensure_cloudinary_configured() -> None:
    api_secret = os.environ.get("CLOUDINARY_API_SECRET")
    if not api_secret:
        raise RuntimeError(
            "CLOUDINARY_API_SECRET is missing. Add it in the Render dashboard and redeploy."
        )

    cloudinary.config(
        cloud_name=CLOUDINARY_CLOUD_NAME,
        api_key=CLOUDINARY_API_KEY,
        api_secret=api_secret,
        secure=True,
    )


def _upload_cloned_audio(audio_path: str, job_id: str) -> str:
    _ensure_cloudinary_configured()
    upload_result = cloudinary.uploader.upload(
        audio_path,
        resource_type="video",
        folder="sayit/cloned-voices",
        public_id=job_id,
        overwrite=True,
    )
    if not upload_result.get("secure_url"):
        raise RuntimeError("Cloudinary did not return a playback URL.")

    mp3_url, _ = cloudinary.utils.cloudinary_url(
        f"sayit/cloned-voices/{job_id}",
        resource_type="video",
        format="mp3",
        secure=True,
    )
    return mp3_url


def _friendly_clone_error(exc: Exception) -> str:
    message = str(exc).strip()
    if not message:
        return "Voice cloning failed after retrying once. Please try again in a minute."

    lower_message = message.lower()
    if "cloudinary_api_secret" in lower_message:
        return message
    if "50 words" in lower_message or "text length" in lower_message:
        return (
            "Please keep cloned-voice text to 50 words or fewer. "
            "The public OpenVoice V2 demo rejected this prompt."
        )
    if "queue" in lower_message or "too many" in lower_message:
        return "The voice model is busy right now. Please tap retry in a minute."
    if "certificate" in lower_message or "ssl" in lower_message:
        return (
            "The server could not securely connect to Hugging Face. "
            "Please try again after redeploying with current dependencies."
        )

    return (
        "Voice cloning failed after retrying once. "
        f"Details: {_clean_space_message(message)}"
    )


def _run_clone_job(job_id: str, text: str, style: str, reference_path: str) -> None:
    job = CLONE_JOBS[job_id]
    cloned_audio_path = None

    try:
        cloned_audio_path, _info = _call_openvoice_with_retry(
            job, text, style, reference_path
        )
        _set_clone_job(job, progress=85, message="Saving cloned audio...")
        audio_url = _upload_cloned_audio(cloned_audio_path, job_id)
        _set_clone_job(
            job,
            status="done",
            progress=100,
            audio_url=audio_url,
            message="Done",
        )
    except Exception as exc:
        _set_clone_job(
            job,
            status="error",
            error=_friendly_clone_error(exc),
            message="Something went wrong.",
        )
    finally:
        _cleanup_file(reference_path)
        if cloned_audio_path:
            _cleanup_file(cloned_audio_path)


@app.route("/")
def index():
    return render_template("index.html", voice_groups=VOICE_GROUPS)


@app.route("/synthesize", methods=["POST"])
def synthesize():
    text = (request.form.get("text") or "").strip()
    voice = request.form.get("voice") or ""

    if not text:
        return jsonify({"error": "Please enter some text first."}), 400

    if voice not in VOICES:
        return jsonify({"error": "Please choose a valid voice."}), 400

    job_id = uuid.uuid4().hex
    filename = f"{job_id}.mp3"
    out_path = os.path.join(OUTPUT_DIR, filename)

    with JOBS_LOCK:
        JOBS[job_id] = {
            "status": "running",
            "bytes_written": 0,
            "estimated_total_bytes": _estimate_total_bytes(text),
            "cancel_event": threading.Event(),
            "audio_url": None,
            "error": None,
        }

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


@app.route("/clone-voice", methods=["POST"])
def clone_voice():
    text = (request.form.get("text") or "").strip()
    style = request.form.get("style") or "en_us"
    consent = request.form.get("consent") == "true"
    audio_file = request.files.get("audio") or request.files.get("reference_audio")

    if not consent:
        return jsonify({"error": "Please confirm you have permission to use this voice sample."}), 400

    text_error = _validate_clone_text(text)
    if text_error:
        return jsonify({"error": text_error}), 400

    if style not in OPENVOICE_STYLES:
        return jsonify({"error": "Please choose a valid language/style."}), 400

    audio_error = _validate_reference_audio(audio_file)
    if audio_error:
        return jsonify({"error": audio_error}), 400

    try:
        reference_path = _save_reference_audio(audio_file)
    except OSError:
        return jsonify({"error": "Could not read that voice sample. Please try again."}), 400

    job_id = uuid.uuid4().hex
    with CLONE_JOBS_LOCK:
        CLONE_JOBS[job_id] = {
            "status": "running",
            "progress": 5,
            "message": "Preparing your voice sample...",
            "audio_url": None,
            "error": None,
        }

    thread = threading.Thread(
        target=_run_clone_job,
        args=(job_id, text, style, reference_path),
        daemon=True,
    )
    thread.start()

    return jsonify({"job_id": job_id}), 202


@app.route("/clone-status/<job_id>")
def clone_status(job_id):
    job = CLONE_JOBS.get(job_id)
    if job is None:
        return jsonify({"error": "Unknown clone job."}), 404

    return jsonify(
        {
            "status": job["status"],
            "progress": job["progress"],
            "message": job["message"],
            "audio_url": job["audio_url"],
            "error": job["error"],
        }
    )


@app.route("/audio/<filename>")
def audio(filename):
    if not FILENAME_PATTERN.match(filename):
        return jsonify({"error": "Invalid filename."}), 400
    return send_from_directory(OUTPUT_DIR, filename)


if __name__ == "__main__":
    app.run(debug=True, port=5000, threaded=True)
