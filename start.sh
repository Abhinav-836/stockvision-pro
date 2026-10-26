#!/usr/bin/env bash
# ===============================================================
# Start script for the StockVision Pro backend (Render / Railway)
#
# The React frontend is deployed separately (e.g. Vercel) with
# VITE_API_URL pointing at this backend. FastAPI does not serve the
# frontend build, so this script only installs and runs the API.
#
# FIXED: the old script built the frontend and copied `build/*` into
# backend/static — but Vite outputs to `dist/`, not `build/`, so the copy
# always failed, and main.py never mounted a static folder anyway. It
# also had no `set -e`, so every one of those failures was silently
# ignored on each deploy.
# ===============================================================
set -euo pipefail

cd "$(dirname "$0")/backend"

echo "Installing backend dependencies..."
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

echo "Starting FastAPI..."
# --proxy-headers lets uvicorn trust the platform's X-Forwarded-* headers.
exec uvicorn main:app --host 0.0.0.0 --port "${PORT:-8000}" --proxy-headers --forwarded-allow-ips="*"