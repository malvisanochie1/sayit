# Free Text-to-Speech Tool

Paste or upload text, pick a voice, and get back a natural-sounding MP3 — 100% free, no API keys, no account, no usage caps. Uses Microsoft Edge's free neural voices via the open-source `edge-tts` library, which sound far more natural than classic robotic TTS.

It also supports free custom voice cloning: record or upload a short sample of a voice, and generate speech in that voice. This is 100% free and cloud-based — no 2GB model is ever downloaded to your computer or to the server this app runs on.

## Run locally

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
4. Run it:
   ```
   python app.py
   ```
   Then open **http://localhost:5000** in your browser.

Custom voice cloning also needs the extra dependencies in `requirements-custom-voice.txt` (`pip install -r requirements-custom-voice.txt`) and the environment variables described below — without them the rest of the app still works, but adding a custom voice will show a friendly "not configured" error.

## Hosting it online for free

The app is designed to run on **[Render](https://render.com)**'s free tier — a real, always-listening web server, unlike Vercel-style platforms which aren't built for a job that needs to keep working and remembering state in the background. Render's free tier sleeps after ~15 minutes idle and takes ~30–60s to wake up on the next visit — normal for a free personal tool.

### Phase A — the app itself (stock voices, cancel, preview)

1. Push this repo to your own GitHub account (fork it, or create an empty repo and push this code to it).
2. Create a free Render account at render.com (signing in with GitHub is simplest).
3. On Render: **New +** → **Web Service** → connect your GitHub repo → set:
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `gunicorn app:app`
   - Instance Type: **Free**
4. Click **Deploy**. Render gives you a live URL (e.g. `your-app.onrender.com`) — that's the hosted app.
5. (Recommended) Add a `SECRET_KEY` environment variable in Render (any long random string) so that custom-voice sessions survive the free server restarting. Without it, a restart resets everyone's private "which voices are mine" cookie (the voices themselves are still safe in cloud storage either way).

### Phase B — custom voice cloning (Hugging Face Space + Cloudinary)

The 2GB voice-cloning model can't fit in Render's free 512MB — so it runs for free on a separate **Hugging Face Space** instead, and Render just calls it over the internet. Saved voices live in **Cloudinary**'s free storage tier, not on Render's disk, so they survive the free server sleeping and restarting.

1. Create a free account at [huggingface.co](https://huggingface.co).
2. Create a new **Space**: SDK = **Gradio**, Hardware = **CPU basic** (free).
3. Upload this repo's `hf_space/app.py` and `hf_space/requirements.txt` into that Space as-is (replacing its defaults). Wait for it to finish building — the first build downloads the XTTS v2 model and can take a while.
4. Note the Space's id, shown as `your-username/your-space-name`.
5. Create a free account at [cloudinary.com](https://cloudinary.com) (no credit card required). From its dashboard, copy the **API Environment variable** value — it looks like `cloudinary://<api_key>:<api_secret>@<cloud_name>`.
6. On Render, add these environment variables to the web service (Settings → Environment):
   | Variable | Value |
   |---|---|
   | `HF_SPACE_NAME` | `your-username/your-space-name` from step 4 |
   | `CLOUDINARY_URL` | the value copied in step 5 |
   | `SECRET_KEY` | a long random string (if not already set in Phase A) |

   (Alternatively, instead of `CLOUDINARY_URL` you can set `CLOUDINARY_CLOUD_NAME`, `CLOUDINARY_API_KEY`, and `CLOUDINARY_API_SECRET` separately — same three values from the Cloudinary dashboard.)
7. Redeploy. Custom voices can now be recorded/uploaded, saved, previewed, deleted, and used to generate speech — all backed by free cloud services, nothing installed on Render itself.

**Free-tier honesty check:** Render's app and the Hugging Face Space both sleep after ~15 minutes idle and take ~30–60s to wake back up on the next request. Cloudinary's free plan is generous (25 credits/month covering storage + bandwidth) but not unlimited. None of this is a real constraint for a personal tool, but it is the honest shape of "free."

## Notes

- An internet connection is required: `edge-tts` reaches Microsoft's free "Read Aloud" voice service, even though there's no API key or cost involved.
- Generated audio files are saved in the local `output/` folder and will accumulate over time — delete them manually whenever you like.
- There's no hard length limit, but the page will show a gentle warning if your text is estimated to produce more than ~6 minutes of audio.
- While generating, a **Cancel** button appears; confirming it stops generation immediately and discards the partial audio.
- Each voice has a **Preview** button next to the dropdown that plays a short pre-made sample, so you can hear a voice before generating your full text.
- Custom voices are private to your browser (via a signed session cookie) — no one else can see, preview, or use a voice you've cloned, even on the same hosted instance.

## Adding or changing voices

If you edit the `VOICES` dict in `app.py`, regenerate the preview samples so the Preview button has something to play for the new voice:

```
python generate_voice_samples.py
```
