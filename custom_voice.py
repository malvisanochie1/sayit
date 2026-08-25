"""Cloud-based custom voice cloning.

Nothing heavy runs here or on the host: voice samples and their metadata
live in Cloudinary (so they survive the free web server sleeping and
restarting), and the actual cloning happens on a separate free Hugging
Face Space, called over the network via gradio_client. This module only
ever handles small text/audio payloads and HTTP calls.

Required environment variables (see README.md):
  - CLOUDINARY_URL  (or CLOUDINARY_CLOUD_NAME + CLOUDINARY_API_KEY + CLOUDINARY_API_SECRET)
  - HF_SPACE_NAME    e.g. "your-username/xtts-voice-clone"
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone

import cloudinary
import cloudinary.api
import cloudinary.exceptions
import cloudinary.uploader
import requests
from gradio_client import Client, handle_file

_METADATA_PUBLIC_ID = "custom_voices/{session_id}/metadata"
_SAMPLE_PUBLIC_ID = "custom_voices/{session_id}/{voice_id}/sample"

# Rough estimate only, used to drive the progress bar while we wait on the
# Hugging Face Space (cloning has no byte-level progress to report).
CLONE_WORDS_PER_MINUTE = 90
ESTIMATED_BYTES_PER_SECOND = 6000

_configured = False
_client = None


class CustomVoiceError(Exception):
    """Raised for user-facing custom-voice failures (not found, misconfigured, etc.)."""


def _configure_cloudinary() -> None:
    global _configured
    if _configured:
        return
    if not os.environ.get("CLOUDINARY_URL"):
        cloud_name = os.environ.get("CLOUDINARY_CLOUD_NAME")
        api_key = os.environ.get("CLOUDINARY_API_KEY")
        api_secret = os.environ.get("CLOUDINARY_API_SECRET")
        if not (cloud_name and api_key and api_secret):
            raise CustomVoiceError(
                "Custom voice storage isn't configured on the server yet "
                "(missing Cloudinary credentials)."
            )
        cloudinary.config(
            cloud_name=cloud_name, api_key=api_key, api_secret=api_secret, secure=True
        )
    _configured = True


def _get_hf_client() -> Client:
    global _client
    if _client is None:
        space = os.environ.get("HF_SPACE_NAME")
        if not space:
            raise CustomVoiceError(
                "Voice cloning isn't configured on the server yet "
                "(missing the Hugging Face Space address)."
            )
        _client = Client(space)
    return _client


def estimate_total_bytes(text: str) -> int:
    word_count = max(len(text.split()), 1)
    estimated_seconds = (word_count / CLONE_WORDS_PER_MINUTE) * 60
    return max(int(estimated_seconds * ESTIMATED_BYTES_PER_SECOND), 1)


def _load_metadata(session_id: str) -> list:
    _configure_cloudinary()
    public_id = _METADATA_PUBLIC_ID.format(session_id=session_id)
    try:
        resource = cloudinary.api.resource(public_id, resource_type="raw")
    except cloudinary.exceptions.NotFound:
        return []
    response = requests.get(resource["secure_url"], timeout=10)
    response.raise_for_status()
    return response.json()


def _save_metadata(session_id: str, voices: list) -> None:
    _configure_cloudinary()
    public_id = _METADATA_PUBLIC_ID.format(session_id=session_id)
    payload = json.dumps(voices).encode("utf-8")
    cloudinary.uploader.upload(
        payload,
        resource_type="raw",
        public_id=public_id,
        overwrite=True,
        invalidate=True,
    )


def list_voices(session_id: str) -> list:
    """Voices belonging to this browser session only (never another session's)."""
    return _load_metadata(session_id)


def add_voice(session_id: str, voice_id: str, name: str, sample_file) -> dict:
    _configure_cloudinary()
    public_id = _SAMPLE_PUBLIC_ID.format(session_id=session_id, voice_id=voice_id)
    upload_result = cloudinary.uploader.upload(
        sample_file,
        resource_type="video",  # Cloudinary stores audio under "video"
        public_id=public_id,
        overwrite=True,
    )

    voices = _load_metadata(session_id)
    record = {
        "id": voice_id,
        "name": name,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "sample_format": upload_result.get("format"),
    }
    voices.append(record)
    _save_metadata(session_id, voices)
    return record


def delete_voice(session_id: str, voice_id: str) -> bool:
    _configure_cloudinary()
    voices = _load_metadata(session_id)
    remaining = [v for v in voices if v["id"] != voice_id]
    if len(remaining) == len(voices):
        return False  # not found / not owned by this session

    public_id = _SAMPLE_PUBLIC_ID.format(session_id=session_id, voice_id=voice_id)
    cloudinary.uploader.destroy(public_id, resource_type="video")
    _save_metadata(session_id, remaining)
    return True


def get_voice(session_id: str, voice_id: str) -> dict | None:
    for voice in _load_metadata(session_id):
        if voice["id"] == voice_id:
            return voice
    return None


def get_sample_bytes(session_id: str, voice_id: str) -> tuple[bytes, str] | None:
    """Returns (audio_bytes, cloudinary_format) for a sample owned by this session."""
    voice = get_voice(session_id, voice_id)
    if voice is None:
        return None
    _configure_cloudinary()
    public_id = _SAMPLE_PUBLIC_ID.format(session_id=session_id, voice_id=voice_id)
    resource = cloudinary.api.resource(public_id, resource_type="video")
    response = requests.get(resource["secure_url"], timeout=15)
    response.raise_for_status()
    return response.content, voice.get("sample_format", "mp3")


def clone_speech(session_id: str, voice_id: str, text: str, job: dict, out_path: str) -> None:
    """Blocking call that clones `text` in the given voice via the Hugging Face
    Space and writes the resulting audio to out_path. Updates `job` in place
    (bytes_written for the progress bar, status/error on completion) the same
    way the stock edge-tts path does, and honours job["cancel_event"].
    """
    voice = get_voice(session_id, voice_id)
    if voice is None:
        job["status"] = "error"
        job["error"] = "That custom voice no longer exists."
        return

    _configure_cloudinary()
    public_id = _SAMPLE_PUBLIC_ID.format(session_id=session_id, voice_id=voice_id)
    sample_resource = cloudinary.api.resource(public_id, resource_type="video")
    sample_url = sample_resource["secure_url"]

    try:
        hf_client = _get_hf_client()
        hf_job = hf_client.submit(text, handle_file(sample_url), api_name="/clone")
    except Exception:
        job["status"] = "error"
        job["error"] = (
            "Couldn't reach the voice cloning service. It runs on a free "
            "Hugging Face Space that may be asleep — please try again in a "
            "minute."
        )
        return

    total = job["estimated_total_bytes"]
    while not hf_job.done():
        if job["cancel_event"].is_set():
            hf_job.cancel()
            job["status"] = "cancelling"
            return
        job["bytes_written"] = min(job["bytes_written"] + total // 20, int(total * 0.9))
        time.sleep(0.5)

    try:
        result_path = hf_job.result()
    except Exception:
        job["status"] = "error"
        job["error"] = (
            "Voice cloning failed on the cloning service — please try again."
        )
        return

    if job["cancel_event"].is_set():
        job["status"] = "cancelling"
        return

    with open(result_path, "rb") as src, open(out_path, "wb") as dst:
        dst.write(src.read())
    job["bytes_written"] = total
