# StockVision Pro 📈
### AI-Powered Stock Analysis for US and Indian Markets

StockVision Pro pulls live quotes, price history and company fundamentals from several free market-data sources, scores each stock with a transparent rule-based model, and adds AI-written commentary through OpenRouter.

## ✨ Features

### 📊 Market data
- **Live prices over WebSocket** for US stocks (Finnhub) and NSE stocks (NSE's own API), with REST polling as a fallback
- **Price charts** for 1D, 5D, 1M, 3M, 6M and 1Y
- **Comparison of 2–5 stocks** side by side, with an overlaid price chart
- **Market ticker** for S&P 500, NASDAQ, Dow Jones, Russell 2000, VIX, NIFTY 50, SENSEX, Bitcoin, gold and crude oil (refreshed every 5 minutes)
- **Watchlist** stored in the browser

### 📈 Analysis
- **Technical:** RSI (14), MACD with signal line, SMA 20/50/200, bull/bear trend classification, annualized volatility from one year of daily returns
- **Fundamental:** P/E, P/B, EPS, ROE, ROA, dividend yield, debt-to-equity, current ratio, revenue and earnings growth, ownership
- **Score (0–100):** weighted rules across valuation, profitability, financial health, income, volatility and technicals, with relaxed P/B scoring for technology stocks and a penalty for yields above 6%
- **Labels:** recommendation, confidence, risk level, growth potential and valuation, derived from the score and metrics

### 🤖 AI (OpenRouter)
- Comparison summary: best for growth, value, income, safest option and top pick
- Investment thesis, natural-language Q&A and news sentiment endpoints
- Model is configurable with `OPENROUTER_MODEL` (default `meta-llama/llama-3.3-70b-instruct:free`)
- If the AI is unavailable or rate-limited, the app falls back to rule-based answers instead of failing

## 🏗 Architecture

```
React (Vite, Recharts) ──REST + WebSocket──▶ FastAPI
                                              │
                ┌─────────────────────────────┼──────────────────────────┐
                ▼                             ▼                          ▼
       Hybrid data engine               In-memory LRU caches       AI service
   NSE API → Finnhub → Alpha Vantage    (quotes 30s, analysis 5m,  OpenRouter, with
   → yFinance, each with timeouts       last-known-good 6h)        response cache and
   and a yFinance circuit breaker                                  per-IP rate limit
```

**Data sources, in the order they are tried**

| Source | Used for | Free-tier limits |
|---|---|---|
| NSE India API | Indian quotes, history, P/E, 52-week range | No key; needs a browser-like session |
| Finnhub | US quotes, company profile | 60 calls/min; no historical candles |
| Alpha Vantage | US fundamentals, last ~100 trading days of history | 25 calls/day |
| yFinance | Everything else (ratios, long history, news) | Unofficial; Yahoo often blocks cloud IPs |

When every live source fails, the API returns the last real data it saw (flagged `is_stale`) or, as a last resort, clearly flagged estimated data (`is_fallback_data`). The UI shows a banner in both cases.

## 🛠 Tech stack

| Layer | Technology |
|---|---|
| Backend | Python 3.11, FastAPI, Uvicorn, pandas, NumPy, aiohttp |
| Market data | yFinance, finnhub-python, Alpha Vantage REST, NSE REST |
| AI | OpenRouter via the `openai` SDK |
| Frontend | React 18, Vite, Recharts |

## 📦 Getting started

### Prerequisites
- Python 3.11+
- Node.js 18+
- Free API keys (optional but recommended): [OpenRouter](https://openrouter.ai), [Finnhub](https://finnhub.io), [Alpha Vantage](https://www.alphavantage.co)

### 1. Clone

```bash
git clone https://github.com/Abhinav-836/stockvision-pro.git
cd stockvision-pro
```

### 2. Backend

```bash
cd backend
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

Create `backend/.env`:

```env
OPENROUTER_API_KEY=your_key
FINNHUB_API_KEY=your_key
ALPHA_VANTAGE_API_KEY=your_key

# Optional
OPENROUTER_MODEL=meta-llama/llama-3.3-70b-instruct:free
ALPHA_VANTAGE_DAILY_LIMIT=25
ALLOWED_ORIGINS=http://localhost:5173
YFINANCE_PROXY_URL=            # http://user:pass@host:port, if Yahoo blocks your host
```

Run it:

```bash
uvicorn main:app --reload
```

The API runs at `http://localhost:8000`, with interactive docs at `http://localhost:8000/api/docs`.

### 3. Frontend

```bash
cd frontend
npm install
echo "VITE_API_URL=http://localhost:8000" > .env
npm run dev
```

Open `http://localhost:5173`.

## 🚀 Deployment
- **Backend:** Render or Railway, start command `bash start.sh` (installs requirements and runs Uvicorn on `$PORT`). Set the same environment variables as `.env`.
- **Frontend:** Vercel, root directory `frontend`, with `VITE_API_URL` set to the backend URL.

## 🔌 Main API endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/api/stock/{symbol}` | Full analysis for one stock |
| GET | `/api/stock/{symbol}/chart?period=1mo` | Price history |
| POST | `/api/ai/compare` | Compare 2–5 stocks with AI summary |
| GET | `/api/ai/thesis/{symbol}` | AI investment thesis |
| POST | `/api/ai/question` | Ask a question, optionally about a stock |
| GET | `/api/market-indices` | Ticker data |
| WS | `/ws` | `{"type": "subscribe", "symbol": "AAPL"}` for live prices |
| GET | `/health` | Health and data-source statistics |

## ⚠️ Disclaimer
StockVision Pro is an educational project. Its scores, labels and AI text are generated from historical data and simple models, are not financial advice, and may be wrong or out of date. Do your own research or consult a registered adviser before investing.