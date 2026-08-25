"""Hugging Face Space: free XTTS v2 voice cloning backend.

This is the piece that needs a real amount of memory (the XTTS v2 model is
~2GB), which is why it runs here — on a free Hugging Face Space, which
gives far more RAM than a free Render web service — instead of on the main
app's server or on anyone's own computer.

Deploy: create a new Space at huggingface.co (SDK: Gradio, Hardware: CPU
basic, free), then upload this file and requirements.txt as-is. The Space
gives you a URL like "your-username/xtts-voice-clone" — put that in the
main app's HF_SPACE_NAME environment variable on Render.

The main app talks to this Space over the network via gradio_client; no
model weights are ever downloaded to the main app's server.
"""

import os
import tempfile

import gradio as gr

# XTTS v2 is released under Coqui's non-commercial license (CPML); running
# it programmatically requires accepting that up front.
os.environ["COQUI_TOS_AGREED"] = "1"

from TTS.api import TTS  # noqa: E402  (import after setting the env var above)

_tts = TTS("tts_models/multilingual/multi-dataset/xtts_v2")


def clone_voice(text: str, speaker_wav: str) -> str:
    if not text or not text.strip():
        raise gr.Error("Please provide some text to speak.")
    if not speaker_wav:
        raise gr.Error("Please provide a voice sample to clone.")

    out_path = os.path.join(tempfile.mkdtemp(), "cloned.wav")
    _tts.tts_to_file(
        text=text.strip(),
        speaker_wav=speaker_wav,
        language="en",
        file_path=out_path,
    )
    return out_path


demo = gr.Interface(
    fn=clone_voice,
    inputs=[
        gr.Textbox(label="Text to speak"),
        gr.Audio(label="Voice sample", type="filepath"),
    ],
    outputs=gr.Audio(label="Cloned speech", type="filepath"),
    api_name="clone",
    title="Free Voice Cloning (XTTS v2)",
    description="Backend Space used by the free-tts-app custom voice feature.",
)

if __name__ == "__main__":
    demo.queue().launch()
