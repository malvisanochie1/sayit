"""One-off script: pre-generates a ~10 second sample clip for every voice in
app.VOICES and saves it under static/voice_samples/<voice_id>.mp3.

Run this once (and again any time VOICES changes) so the in-app voice
preview button has something to play without hitting edge-tts on every click:

    python generate_voice_samples.py
"""

import asyncio
import os

import edge_tts

from app import VOICES, get_voice_synthesis_options

SAMPLE_TEXT = (
    "In the quiet hour before dawn, every shadow held its breath. "
    "This is a storytelling preview, tuned for a deep, natural narration."
)

SAMPLES_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "static", "voice_samples"
)


async def _generate_all() -> None:
    os.makedirs(SAMPLES_DIR, exist_ok=True)
    for voice_id, label in VOICES.items():
        out_path = os.path.join(SAMPLES_DIR, f"{voice_id}.mp3")
        if os.path.exists(out_path):
            print(f"Skipping existing sample for {label} ({voice_id}).")
            continue
        print(f"Generating sample for {label} ({voice_id})...")
        communicate = edge_tts.Communicate(SAMPLE_TEXT, **get_voice_synthesis_options(voice_id))
        await communicate.save(out_path)
    print("Done.")


if __name__ == "__main__":
    asyncio.run(_generate_all())
