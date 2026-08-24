# Free Text-to-Speech Tool

Paste or upload text, pick a voice, and get back a natural-sounding MP3 — 100% free, no API keys, no account, no usage caps. Uses Microsoft Edge's free neural voices via the open-source `edge-tts` library, which sound far more natural than classic robotic TTS.

## Setup

1. Make sure Python 3.8+ is installed.
2. (Optional but recommended) Create a virtual environment:
   ```
   python -m venv venv
   venv\Scripts\activate
   ```
3. Install dependencies:
   ```
   pip install -r requirements.txt
   ```

## Run

```
python app.py
```

Then open **http://localhost:5000** in your browser.

## Notes

- An internet connection is required: `edge-tts` reaches Microsoft's free "Read Aloud" voice service, even though there's no API key or cost involved.
- Generated audio files are saved in the local `output/` folder and will accumulate over time — delete them manually whenever you like.
- There's no hard length limit, but the page will show a gentle warning if your text is estimated to produce more than ~6 minutes of audio.
- While generating, a **Cancel** button appears; confirming it stops generation immediately and discards the partial audio.
- Each voice has a **Preview** button next to the dropdown that plays a short pre-made sample, so you can hear a voice before generating your full text.

## Adding or changing voices

If you edit the `VOICES` dict in `app.py`, regenerate the preview samples so the Preview button has something to play for the new voice:

```
python generate_voice_samples.py
```
