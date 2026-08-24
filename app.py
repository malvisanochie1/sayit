import asyncio
import os
import re
import threading
import uuid

import edge_tts
from flask import Flask, jsonify, render_template, request, send_from_directory

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

# Rough estimate used only to drive the progress bar (not exact):
# edge-tts's neural voices produce audio at roughly 48kbps.
WORDS_PER_MINUTE = 140
ESTIMATED_BYTES_PER_SECOND = 6000

JOBS = {}
JOBS_LOCK = threading.Lock()


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


@app.route("/audio/<filename>")
def audio(filename):
    if not FILENAME_PATTERN.match(filename):
        return jsonify({"error": "Invalid filename."}), 400
    return send_from_directory(OUTPUT_DIR, filename)


if __name__ == "__main__":
    app.run(debug=True, port=5000, threaded=True)
