# StockVision Pro

AI-powered stock analysis platform with real-time price data, interactive charts, and AI-generated investment insights.

## Features
- Real-time stock prices via WebSocket, with automatic REST polling fallback
- AI-powered investment analysis (score, recommendation, risk, valuation) via OpenRouter (Llama 3.3)
- Interactive price charts across 6 timeframes (1D–1Y)
- Multi-stock comparison with AI-driven "best for growth/value/income" analysis
- Watchlist management (stored client-side)
- Indian stock market support (NSE/BSE symbols)
- Three-tier data sourcing with automatic fallback (see Architecture below)

## Tech Stack
- **Backend**: FastAPI, yFinance, Finnhub, Alpha Vantage, WebSocket
- **Frontend**: React, Recharts, Vite
- **AI**: OpenRouter API (Llama 3.3, free tier)
- **Caching**: In-memory (`LRUCache`) — no external cache/database required

## Architecture: Hybrid Data Engine

Stock quotes, historical data, and company fundamentals are fetched through a cascading fallback chain, tried in order until one succeeds:

1. **Finnhub** (fastest, best for live quotes — free tier does *not* include historical candles)
2. **Alpha Vantage** (best fundamentals — free tier is a strict **25 requests/day**, 1/second)
3. **yFinance** (no key required, unofficial/scraped — most reliable for historical charts, but can be rate-limited or blocked by Yahoo intermittently)

If all three fail for a given request, a clearly-flagged synthetic/estimated dataset is returned rather than an error, so the UI never shows a broken page — check the response's `is_fallback_data` / `is_stale` fields (or the on-screen banner) to know whether you're looking at live, stale-but-real, or estimated data.

**Practical implication:** on the free tiers, expect Finnhub to handle quotes, yFinance to fill in most historical charts, and Alpha Vantage to be the most rate-limited of the three — don't be surprised seeing `Alpha Vantage rejected` warnings in the logs after a handful of requests in the same day.

## Quick Start

### Backend

```bash
cd backend
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # macOS/Linux

pip install -r requirements.txt
```

Create `backend/.env`:

```env
# AI analysis (required for AI Score/Recommendation)
OPENROUTER_API_KEY=your_key_here
OPENROUTER_MODEL=meta-llama/llama-3.3-70b-instruct:free
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
APP_URL=http://localhost:5173
AI_CACHE_TTL=900

# Live data sources (optional but strongly recommended — without these
# the app runs on yFinance alone, which is the least reliable tier)
FINNHUB_API_KEY=your_key_here          # free at finnhub.io
ALPHA_VANTAGE_API_KEY=your_key_here    # free at alphavantage.co
ALPHA_VANTAGE_DAILY_LIMIT=25           # raise only if you're on a paid AV plan

# Server config
CACHE_TTL=300
MAX_COMPARISON_STOCKS=5
MIN_COMPARISON_STOCKS=2
ALLOWED_ORIGINS=http://localhost:5173,http://localhost:3000
```

Run it:

```bash
uvicorn main:app --reload
```

### Frontend

```bash
cd frontend
npm install
```

Create `frontend/.env`:

```env
VITE_API_URL=http://localhost:8000
```

> **⚠️ The single most common source of "nothing works" bugs in this project:** this file must point at `http://localhost:8000` for local development and at your deployed backend URL (e.g. `https://your-app.onrender.com`) for production. If you leave your production URL in here while developing locally, your frontend will silently talk to the deployed backend instead of the one on your machine — every fix you make locally will appear to do nothing, because the app was never talking to your local server in the first place. Vite also only reads this file at startup, not on hot-reload — restart `npm run dev` after changing it.

Run it:

```bash
npm run dev
```

## API Documentation
- Swagger UI: `http://localhost:8000/api/docs`
- ReDoc: `http://localhost:8000/api/redoc`
- Quick diagnostic (tests all 3 data sources for a symbol directly): `http://localhost:8000/api/debug/{symbol}`

## Deployment (Render)

`render.yaml`:

```yaml
services:
  - type: web
    name: stockvision-backend
    env: python
    buildCommand: pip install -r requirements.txt
    startCommand: uvicorn main:app --host 0.0.0.0 --port $PORT
    envVars:
      - key: OPENROUTER_API_KEY
        sync: false
      - key: FINNHUB_API_KEY
        sync: false
      - key: ALPHA_VANTAGE_API_KEY
        sync: false
      - key: CACHE_TTL
        value: 300
      - key: ALLOWED_ORIGINS
        value: https://your-frontend-url.onrender.com

  - type: web
    name: stockvision-frontend
    env: static
    buildCommand: cd frontend && npm install && npm run build
    staticPublishPath: ./frontend/dist
    envVars:
      - key: VITE_API_URL
        value: https://stockvision-backend.onrender.com   # ← must match your actual backend service URL
```

**Before deploying, set `FINNHUB_API_KEY` and `ALPHA_VANTAGE_API_KEY` in Render's dashboard** (Environment tab) — these are separate from your local `.env` and won't be picked up automatically. Without them, production silently falls back to yFinance-only, which is the flakiest tier.

**Render's free tier spins down when idle.** The first request after a period of inactivity can take 30–60+ seconds to cold-start — this is a platform limitation, not an application bug. Subsequent requests will be fast.

## Known Limitations
- Finnhub's free tier returns `403` on historical candle data — quotes and company profile still work.
- Alpha Vantage's free tier is capped at 25 requests/day — expect it to be exhausted quickly during active development/testing.
- yFinance is unofficial and can be intermittently rate-limited or blocked by Yahoo with no advance notice; this is why the app is built to cascade through 3 sources rather than depend on any single one.
- Watchlist is stored in browser `localStorage`, not synced across devices.

## License
MIT