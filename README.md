
# AI-Fake Blocker API (Deployable)

This is a minimal FastAPI service with CORS enabled so your Chrome extension can call it.

## Local run
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app:app --reload --host 0.0.0.0 --port 8000
```

## Deploy on Render (easiest)
1. Push these files to a new GitHub repo.
2. Go to https://render.com → New → **Blueprint** → connect the repo (it will read `render.yaml`).
3. Click **Deploy**. Wait for the URL like `https://aifake-blocker-api.onrender.com`.
4. Your endpoint will be: `https://aifake-blocker-api.onrender.com/score`

## Deploy on Railway (also simple)
1. Push to a GitHub repo.
2. Go to https://railway.app → New Project → **Deploy from GitHub repo**.
3. Railway auto-detects the Python service. Set start command to:
   `uvicorn app:app --host 0.0.0.0 --port $PORT`
4. Once deployed, copy the URL shown (e.g., `https://aifake-blocker.up.railway.app/score`).

## Configure your extension
Paste your deployed URL into the extension popup:
```
https://YOUR-HOSTNAME/score
```
