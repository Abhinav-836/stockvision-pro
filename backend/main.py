# backend/main.py
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, field_validator, Field
from typing import List, Optional, Dict, Any
from datetime import datetime
import yfinance as yf
import numpy as np
import asyncio
import logging
from collections import OrderedDict
import time
import re
import os
import json
from collections import deque
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

load_dotenv()

# ---------------------------------------------------------------------------
# Local imports
# ---------------------------------------------------------------------------
from financials import (
    calculate_pe_ratio, calculate_pb_ratio, calculate_debt_to_equity,
    calculate_current_ratio, calculate_roe, calculate_roa,
    get_dividend_yield, calculate_eps, analyze_growth,
    calculate_volatility, get_ownership_pattern,
    calculate_technical_indicators, get_latest_news,
    calculate_ai_score, generate_recommendation,
    is_indian_stock, normalize_indian_symbol
)
from ai_service import ai_service


# ---------------------------------------------------------------------------
# Rate Limiter for yFinance
# ---------------------------------------------------------------------------

class yFinanceRateLimiter:
    """Rate limiter for yFinance API calls to prevent "Too Many Requests" errors"""
    def __init__(self, max_calls: int = 8, time_window: int = 60):
        self.max_calls = max_calls
        self.time_window = time_window
        self.calls = deque()
    
    def can_call(self) -> bool:
        now = time.time()
        # Remove calls outside time window
        while self.calls and self.calls[0] < now - self.time_window:
            self.calls.popleft()
        
        if len(self.calls) >= self.max_calls:
            return False
        self.calls.append(now)
        return True
    
    async def wait_if_needed(self):
        """Wait if rate limit is hit (async version)"""
        if not self.can_call():
            wait_time = self.time_window - (time.time() - self.calls[0])
            if wait_time > 0:
                logger.warning(f"Rate limit reached, waiting {wait_time:.1f}s...")
                await asyncio.sleep(wait_time)
            self.calls.popleft()
            self.calls.append(time.time())

# Create global rate limiter
yf_limiter = yFinanceRateLimiter(max_calls=8, time_window=60)


# ---------------------------------------------------------------------------
# WebSocket connection manager
# ---------------------------------------------------------------------------
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self.subscriptions: Dict[str, List[WebSocket]] = {}

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active_connections.append(ws)

    def disconnect(self, ws: WebSocket):
        if ws in self.active_connections:
            self.active_connections.remove(ws)
        for symbol in list(self.subscriptions.keys()):
            if ws in self.subscriptions[symbol]:
                self.subscriptions[symbol].remove(ws)

    async def subscribe(self, ws: WebSocket, symbol: str):
        self.subscriptions.setdefault(symbol, []).append(ws)

    async def broadcast_to_symbol(self, symbol: str, message: dict):
        dead: List[WebSocket] = []
        for ws in self.subscriptions.get(symbol, []):
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

    async def broadcast_all(self, message: dict):
        dead: List[WebSocket] = []
        for ws in self.active_connections:
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


manager = ConnectionManager()


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
class Config:
    API_TITLE               = "StockVision Pro API"
    API_VERSION             = "2.2.0"
    CACHE_TTL               = int(os.getenv("CACHE_TTL", 60))
    MAX_CACHE_SIZE          = 1000
    RATE_LIMIT_REQUESTS     = int(os.getenv("RATE_LIMIT_REQUESTS", 100))
    RATE_LIMIT_WINDOW       = int(os.getenv("RATE_LIMIT_WINDOW", 60))
    MAX_COMPARISON_STOCKS   = int(os.getenv("MAX_COMPARISON_STOCKS", 5))
    MIN_COMPARISON_STOCKS   = int(os.getenv("MIN_COMPARISON_STOCKS", 2))
    ALLOWED_ORIGINS         = os.getenv(
        "ALLOWED_ORIGINS",
        "http://localhost:5173,http://localhost:3000,https://stockvision-pro-sigma.vercel.app/"
    ).split(",")
    REDIS_HOST  = os.getenv("REDIS_HOST", "localhost")
    REDIS_PORT  = int(os.getenv("REDIS_PORT", 6379))
    REDIS_DB    = int(os.getenv("REDIS_DB", 0))

config = Config()


# ---------------------------------------------------------------------------
# LRU Cache
# ---------------------------------------------------------------------------
class LRUCache:
    def __init__(self, max_size: int = 1000, ttl: int = 300):
        self.cache:      OrderedDict = OrderedDict()
        self.timestamps: Dict[str, float] = {}
        self.max_size    = max_size
        self.ttl         = ttl
        self.hits        = 0
        self.misses      = 0

    def get(self, key: str):
        if key not in self.cache:
            self.misses += 1
            return None
        if time.time() - self.timestamps[key] > self.ttl:
            self._delete(key)
            self.misses += 1
            return None
        self.cache.move_to_end(key)
        self.hits += 1
        return self.cache[key]

    def set(self, key: str, value):
        if key in self.cache:
            self.cache.move_to_end(key)
        self.cache[key] = value
        self.timestamps[key] = time.time()
        if len(self.cache) > self.max_size:
            oldest = next(iter(self.cache))
            self._delete(oldest)

    def _delete(self, key: str):
        self.cache.pop(key, None)
        self.timestamps.pop(key, None)

    def delete(self, key: str):
        self._delete(key)

    def delete_pattern(self, pattern: str):
        for key in [k for k in self.cache if pattern in k]:
            self._delete(key)

    def clear(self):
        self.cache.clear()
        self.timestamps.clear()

    def stats(self) -> Dict:
        total    = self.hits + self.misses
        hit_rate = (self.hits / total * 100) if total else 0
        return {
            "size":      len(self.cache),
            "hits":      self.hits,
            "misses":    self.misses,
            "hit_rate":  f"{hit_rate:.2f}%",
            "max_size":  self.max_size,
        }


stock_cache = LRUCache(max_size=config.MAX_CACHE_SIZE, ttl=config.CACHE_TTL)
chart_cache = LRUCache(max_size=config.MAX_CACHE_SIZE, ttl=config.CACHE_TTL)


# ---------------------------------------------------------------------------
# Background tasks
# ---------------------------------------------------------------------------
async def market_updater():
    """Refresh market indices every 60 s and push via WebSocket."""
    while True:
        try:
            stock_cache.delete_pattern("market:indices")
            indices = await get_market_indices(use_cache=False)
            await manager.broadcast_all({
                "type":      "market_update",
                "data":      indices,
                "timestamp": datetime.now().isoformat(),
            })
            logger.info("Market indices pushed via WebSocket")
        except Exception as e:
            logger.error(f"market_updater error: {e}")
        await asyncio.sleep(60)


async def price_updater():
    """Push live prices to subscribed clients every 5 s."""
    while True:
        try:
            for symbol in list(manager.subscriptions.keys()):
                if not manager.subscriptions.get(symbol):
                    continue
                try:
                    await yf_limiter.wait_if_needed()
                    loop = asyncio.get_event_loop()
                    stock = await loop.run_in_executor(None, yf.Ticker, symbol)
                    hist = await loop.run_in_executor(
                        None, lambda: stock.history(period="1d", interval="1m")
                    )
                    if hist is not None and not hist.empty:
                        cur = float(hist['Close'].iloc[-1])
                        prev = float(hist['Close'].iloc[-2]) if len(hist) > 1 else cur
                        chg = ((cur - prev) / prev * 100) if prev else 0
                        await manager.broadcast_to_symbol(symbol, {
                            "type":      "price_update",
                            "symbol":    symbol,
                            "price":     round(cur, 2),
                            "change":    round(chg, 2),
                            "timestamp": datetime.now().isoformat(),
                        })
                except Exception as e:
                    logger.error(f"price_updater error for {symbol}: {e}")
        except Exception as e:
            logger.error(f"price_updater outer error: {e}")
        await asyncio.sleep(5)


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    asyncio.create_task(market_updater())
    asyncio.create_task(price_updater())
    logger.info("✅ Background tasks started")
    yield
    logger.info("API shutting down")


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(
    title=config.API_TITLE,
    version=config.API_VERSION,
    description="StockVision Pro — AI-powered stock analysis",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Validation models
# ---------------------------------------------------------------------------

_SYMBOL_RE = re.compile(r'^[A-Z0-9]{1,10}(\.[A-Z]{2,3})?$')


class StockRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=15)

    @field_validator('symbol')
    @classmethod
    def validate_symbol(cls, v: str) -> str:
        v = v.upper().strip()
        if not _SYMBOL_RE.match(v):
            raise ValueError(
                'Invalid symbol. Use up to 10 uppercase letters/digits, '
                'optionally with a .NS / .BO suffix.'
            )
        return v


class CompareRequest(BaseModel):
    symbols: List[str] = Field(..., min_length=2, max_length=5)

    @field_validator('symbols')
    @classmethod
    def validate_symbols(cls, v: List[str]) -> List[str]:
        if len(v) < config.MIN_COMPARISON_STOCKS:
            raise ValueError(f'At least {config.MIN_COMPARISON_STOCKS} symbols required')
        if len(v) > config.MAX_COMPARISON_STOCKS:
            raise ValueError(f'Maximum {config.MAX_COMPARISON_STOCKS} symbols allowed')

        cleaned = []
        for sym in v:
            sym = sym.upper().strip()
            if not _SYMBOL_RE.match(sym):
                raise ValueError(f'Invalid symbol: {sym}')
            cleaned.append(sym)

        if len(cleaned) != len(set(cleaned)):
            raise ValueError('Duplicate symbols detected')
        return cleaned


# ---------------------------------------------------------------------------
# WebSocket endpoint
# ---------------------------------------------------------------------------
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
                mtype = msg.get('type')
                if mtype == 'subscribe':
                    sym = msg.get('symbol')
                    if sym:
                        await manager.subscribe(websocket, sym.upper())
                        await websocket.send_json({"type": "subscribed", "symbol": sym, "status": "success"})
                elif mtype == 'unsubscribe':
                    sym = msg.get('symbol', '').upper()
                    if sym in manager.subscriptions and websocket in manager.subscriptions[sym]:
                        manager.subscriptions[sym].remove(websocket)
            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "message": "Invalid JSON"})
    except WebSocketDisconnect:
        manager.disconnect(websocket)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def safe_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def safe_get(d: Optional[Dict], key: str, default: Any = None) -> Any:
    return d.get(key, default) if d else default


def invalidate_symbol_cache(symbol: str):
    stock_cache.delete_pattern(symbol)
    chart_cache.delete_pattern(symbol)
    logger.info(f"Cache invalidated for {symbol}")


async def fetch_stock_data(symbol: str, use_cache: bool = True) -> tuple:
    """Fetch ticker, info dict, and 1-year history from yFinance with rate limiting."""
    cache_key = f"stock_data:{symbol}"

    if use_cache:
        cached = stock_cache.get(cache_key)
        if cached:
            logger.info(f"Cache hit for {symbol}")
            return cached

    loop = asyncio.get_event_loop()
    logger.info(f"Fetching fresh data for {symbol}")
    
    # Apply rate limiting
    await yf_limiter.wait_if_needed()

    # -- Ticker --------------------------------------------------------------
    try:
        stock = await loop.run_in_executor(None, yf.Ticker, symbol)
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Could not create ticker for {symbol}: {e}")

    # -- Info ----------------------------------------------------------------
    try:
        info = await asyncio.wait_for(
            loop.run_in_executor(None, lambda: stock.info or {}),
            timeout=10.0
        )
    except asyncio.TimeoutError:
        logger.error(f"Timeout fetching info for {symbol}")
        info = {}
    except Exception as e:
        logger.error(f"Error fetching info for {symbol}: {e}")
        info = {}

    # -- Auto-retry with .NS suffix for Indian stocks -----------------------
    if (not info or len(info) < 5) and not symbol.endswith(('.NS', '.BO')):
        alt = symbol + '.NS'
        try:
            await yf_limiter.wait_if_needed()
            alt_stock = await loop.run_in_executor(None, yf.Ticker, alt)
            alt_info = await asyncio.wait_for(
                loop.run_in_executor(None, lambda: alt_stock.info or {}),
                timeout=10.0
            )
            if alt_info and len(alt_info) > 5:
                logger.info(f"Resolved {symbol} → {alt}")
                stock = alt_stock
                info = alt_info
                symbol = alt
        except Exception:
            pass

    # -- History with retry on rate limit ------------------------------------
    max_retries = 3
    hist = None
    for attempt in range(max_retries):
        try:
            await yf_limiter.wait_if_needed()
            hist = await asyncio.wait_for(
                loop.run_in_executor(None, lambda: stock.history(period="1y")),
                timeout=15.0
            )
            break
        except Exception as e:
            error_msg = str(e)
            if "Rate limited" in error_msg or "Too Many Requests" in error_msg:
                if attempt < max_retries - 1:
                    wait_time = 5 * (attempt + 1)
                    logger.warning(f"Rate limited for {symbol}, waiting {wait_time}s... (attempt {attempt + 1}/{max_retries})")
                    await asyncio.sleep(wait_time)
                    continue
            if attempt == max_retries - 1:
                raise HTTPException(status_code=429, detail=f"Rate limited. Please try again later for {symbol}")

    if hist is None or hist.empty:
        raise HTTPException(status_code=404, detail=f"No historical data available for {symbol}")

    result = (stock, info, hist)
    if use_cache:
        stock_cache.set(cache_key, result)

    logger.info(f"Data fetched for {symbol}")
    return result


def calculate_price_metrics(info: Dict, hist) -> Dict:
    """Extract current price and daily change."""
    try:
        current_price = safe_float(
            info.get('currentPrice') or
            info.get('regularMarketPrice') or
            info.get('previousClose') or
            (hist['Close'].iloc[-1] if len(hist) > 0 else 0.0)
        )
        previous_close = safe_float(
            info.get('previousClose') or
            (hist['Close'].iloc[-2] if len(hist) > 1 else current_price)
        )
        change = current_price - previous_close
        change_percent = ((change / previous_close) * 100) if previous_close else 0.0

        return {
            "current_price": round(current_price, 2),
            "previous_close": round(previous_close, 2),
            "change": round(change, 2),
            "change_percent": round(change_percent, 2),
            "day_high": round(safe_float(info.get('dayHigh') or hist['High'].iloc[-1]), 2),
            "day_low": round(safe_float(info.get('dayLow') or hist['Low'].iloc[-1]), 2),
            "volume": safe_float(info.get('volume', 0)),
        }
    except Exception as e:
        logger.error(f"Error in calculate_price_metrics: {e}")
        return {k: 0.0 for k in ("current_price", "previous_close", "change",
                                  "change_percent", "day_high", "day_low", "volume")}


def build_stock_response(symbol: str, stock, info: Dict, hist) -> Dict:
    """Assemble the full stock response object."""
    price_m = calculate_price_metrics(info, hist)
    pe = calculate_pe_ratio(info)
    pb = calculate_pb_ratio(info)
    de = calculate_debt_to_equity(info)
    cr = calculate_current_ratio(info)
    roe = calculate_roe(info)
    roa = calculate_roa(info)
    div = get_dividend_yield(info)
    eps = calculate_eps(info)
    vol = calculate_volatility(hist)
    tech = calculate_technical_indicators(hist)
    growth = analyze_growth(stock)
    ownership = get_ownership_pattern(stock)
    news = get_latest_news(symbol)
    sector = safe_get(info, 'sector')
    
    metrics = {
        'pe_ratio': pe, 'pb_ratio': pb, 'dividend_yield': div,
        'debt_to_equity': de, 'eps': eps, 'roe': roe, 'roa': roa,
        'current_ratio': cr, 'volatility': vol,
        'growth_metrics': growth, 'technical_indicators': tech,
        'sector': sector,
    }

    ai_score = calculate_ai_score(metrics)
    rec_data = generate_recommendation(ai_score, metrics)

    is_indian = is_indian_stock(symbol)
    display_symbol = normalize_indian_symbol(symbol) if is_indian else symbol
    company_name = (
        safe_get(info, 'longName') or
        safe_get(info, 'shortName') or
        display_symbol
    )

    return {
        "symbol": display_symbol,
        "original_symbol": symbol,
        "is_indian_stock": is_indian,
        "company_name": company_name,
        **price_m,
        "market_cap": safe_float(safe_get(info, 'marketCap', 0)),
        "pe_ratio": round(pe, 2) if pe is not None else None,
        "pb_ratio": round(pb, 2) if pb is not None else None,
        "dividend_yield": round(div, 2) if div is not None else None,
        "debt_to_equity": round(de, 2) if de is not None else None,
        "eps": round(eps, 2) if eps is not None else None,
        "roe": round(roe, 2) if roe is not None else None,
        "roa": round(roa, 2) if roa is not None else None,
        "current_ratio": round(cr, 2) if cr is not None else None,
        "volatility": round(vol, 4),
        "fifty_two_week_high": safe_float(safe_get(info, 'fiftyTwoWeekHigh', 0)),
        "fifty_two_week_low": safe_float(safe_get(info, 'fiftyTwoWeekLow', 0)),
        "average_volume": safe_float(safe_get(info, 'averageVolume', 0)),
        "sector": sector,
        "industry": safe_get(info, 'industry'),
        "exchange": safe_get(info, 'exchange'),
        "ai_score": round(ai_score, 2),
        "recommendation": rec_data.get('recommendation', 'Hold'),
        "confidence": rec_data.get('confidence', 'Moderate'),
        "risk_level": rec_data.get('risk_level', 'Moderate Risk'),
        "growth_potential": rec_data.get('growth_potential', 'Moderate Growth'),
        "valuation": rec_data.get('valuation', 'Fairly Valued'),
        "technical_indicators": tech,
        "news": news[:5],
        "ownership": ownership,
        "growth_metrics": growth,
        "last_updated": datetime.now().isoformat(),
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/")
async def root():
    return {
        "service": config.API_TITLE,
        "version": config.API_VERSION,
        "status": "operational",
        "timestamp": datetime.now().isoformat(),
        "endpoints": {
            "health": "/health",
            "stock": "/api/stock/{symbol}",
            "chart": "/api/stock/{symbol}/chart",
            "compare": "/api/compare",
            "ai_compare": "/api/ai/compare",
            "ai_thesis": "/api/ai/thesis/{symbol}",
            "ai_question": "/api/ai/question",
            "ai_sentiment": "/api/ai/sentiment",
            "trending": "/api/trending",
            "market": "/api/market-indices",
            "search": "/api/search/{query}",
            "docs": "/api/docs",
            "websocket": "/ws",
        },
    }


@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "version": config.API_VERSION,
        "cache_stats": stock_cache.stats(),
        "ai_model": ai_service.model,
        "rate_limits": ai_service.get_rate_limit_stats(),
    }


@app.post("/api/cache/invalidate/{symbol}")
async def invalidate_cache(symbol: str):
    try:
        invalidate_symbol_cache(symbol.upper().strip())
        return {"status": "success", "message": f"Cache cleared for {symbol}", "timestamp": datetime.now().isoformat()}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/api/debug/{symbol}")
async def debug_stock(symbol: str):
    """Diagnostic endpoint — check yFinance connectivity for a symbol."""
    symbol = symbol.upper().strip()
    result: Dict = {"symbol": symbol, "timestamp": datetime.now().isoformat(), "tests": []}

    try:
        stock = yf.Ticker(symbol)
        result["tests"].append({"name": "create_ticker", "success": True})
    except Exception as e:
        result["tests"].append({"name": "create_ticker", "success": False, "error": str(e)})
        return result

    try:
        info = stock.info or {}
        result["tests"].append({
            "name": "get_info", "success": bool(info and len(info) > 5),
            "keys": len(info), "sample": list(info.keys())[:8],
        })
    except Exception as e:
        result["tests"].append({"name": "get_info", "success": False, "error": str(e)})

    try:
        hist = stock.history(period="1mo")
        result["tests"].append({
            "name": "get_history", "success": not (hist is None or hist.empty),
            "rows": len(hist) if hist is not None else 0,
        })
    except Exception as e:
        result["tests"].append({"name": "get_history", "success": False, "error": str(e)})

    if not symbol.endswith(('.NS', '.BO')):
        alt = symbol + '.NS'
        try:
            alt_info = yf.Ticker(alt).info or {}
            if len(alt_info) > 5:
                result["tests"].append({"name": "alt_symbol_ns", "success": True, "alt": alt})
        except Exception:
            pass

    return result


@app.get("/api/stock/{symbol}")
async def get_stock_analysis(symbol: str, use_cache: bool = True):
    """Full stock analysis — financials, AI score, technicals, news."""
    symbol = symbol.upper().strip()
    cache_key = f"stock:{symbol}"

    if use_cache:
        cached = stock_cache.get(cache_key)
        if cached:
            return cached

    stock, info, hist = await fetch_stock_data(symbol, use_cache=False)
    data = build_stock_response(symbol, stock, info, hist)

    if use_cache:
        stock_cache.set(cache_key, data)

    return data


@app.get("/api/stock/{symbol}/chart")
async def get_stock_chart(symbol: str, period: str = "1mo", use_cache: bool = True):
    """OHLCV chart data for a given period."""
    symbol = symbol.upper().strip()
    valid_periods = {"1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y", "max"}
    if period not in valid_periods:
        period = "1mo"

    cache_key = f"chart:{symbol}:{period}"
    if use_cache:
        cached = chart_cache.get(cache_key)
        if cached:
            return cached

    await yf_limiter.wait_if_needed()
    loop = asyncio.get_event_loop()
    stock = await loop.run_in_executor(None, yf.Ticker, symbol)
    hist = await loop.run_in_executor(None, lambda: stock.history(period=period))

    if hist is None or hist.empty:
        raise HTTPException(status_code=404, detail=f"No chart data for {symbol}")

    chart_data = [
        {
            "date": date.isoformat(),
            "price": round(float(row['Close']), 2),
            "open": round(float(row['Open']), 2),
            "high": round(float(row['High']), 2),
            "low": round(float(row['Low']), 2),
            "volume": int(row.get('Volume', 0)),
        }
        for date, row in hist.iterrows()
    ]

    if use_cache:
        chart_cache.set(cache_key, chart_data)

    return chart_data


@app.post("/api/compare")
async def compare_stocks(request: CompareRequest):
    """Rule-based multi-stock comparison (no AI call)."""
    results = await asyncio.gather(
        *[fetch_stock_data(s) for s in request.symbols],
        return_exceptions=True
    )

    stocks_data: List[Dict] = []
    failed: List[str] = []

    for i, res in enumerate(results):
        if isinstance(res, Exception):
            failed.append(f"{request.symbols[i]}: {res}")
            continue
        stock, info, hist = res
        stocks_data.append(build_stock_response(request.symbols[i], stock, info, hist))

    if len(stocks_data) < config.MIN_COMPARISON_STOCKS:
        raise HTTPException(
            status_code=400,
            detail=f"Need at least {config.MIN_COMPARISON_STOCKS} valid stocks. Failed: {', '.join(failed)}"
        )

    valid_pe = [s for s in stocks_data if s.get('pe_ratio') is not None]
    valid_roe = [s for s in stocks_data if s.get('roe') is not None]
    valid_div = [s for s in stocks_data if s.get('dividend_yield') is not None]
    valid_vol = [s for s in stocks_data if s.get('volatility') is not None]
    valid_de = [s for s in stocks_data if s.get('debt_to_equity') is not None]

    comparison = {
        "ai_top_pick": max(stocks_data, key=lambda x: x['ai_score'])['symbol'],
        "best_value": min(valid_pe, key=lambda x: x['pe_ratio'])['symbol'] if valid_pe else "N/A",
        "best_dividend": max(valid_div, key=lambda x: x['dividend_yield'])['symbol'] if valid_div else "N/A",
        "lowest_risk": min(valid_vol, key=lambda x: x['volatility'])['symbol'] if valid_vol else "N/A",
        "average_pe": round(np.mean([s['pe_ratio'] for s in valid_pe]), 2) if valid_pe else 0,
        "average_roe": round(np.mean([s['roe'] for s in valid_roe]), 2) if valid_roe else 0,
        "average_div": round(np.mean([s['dividend_yield'] for s in valid_div]), 2) if valid_div else 0,
        "average_volatility": round(np.mean([s['volatility'] for s in valid_vol]), 2) if valid_vol else 0,
        "average_debt": round(np.mean([s['debt_to_equity'] for s in valid_de]), 2) if valid_de else 0,
        "successful_symbols": [s['symbol'] for s in stocks_data],
        "failed_symbols": failed,
    }

    return {"stocks": stocks_data, "comparison": comparison}


@app.post("/api/ai/compare")
async def ai_compare_stocks(request: CompareRequest, req: Request = None):
    """AI-powered stock comparison using DeepSeek R1."""
    user_id = req.client.host if req and req.client else "anonymous"

    results = await asyncio.gather(
        *[fetch_stock_data(s) for s in request.symbols],
        return_exceptions=True
    )

    stocks_data: List[Dict] = []
    failed: List[str] = []

    for i, res in enumerate(results):
        if isinstance(res, Exception):
            failed.append(request.symbols[i])
            continue
        stock, info, hist = res
        stocks_data.append(build_stock_response(request.symbols[i], stock, info, hist))

    if len(stocks_data) < 2:
        return {"success": False, "error": "Need at least 2 valid stocks", "failed_symbols": failed}

    ai_analysis = await ai_service.analyze_stock_comparison(stocks_data, user_id=user_id)

    return {
        "success": True,
        "stocks": stocks_data,
        "ai_analysis": ai_analysis,
        "failed_symbols": failed,
        "rate_limit": ai_service.get_rate_limit_stats(),
        "timestamp": datetime.now().isoformat(),
    }


@app.get("/api/ai/thesis/{symbol}")
async def get_ai_thesis(symbol: str, req: Request = None):
    """DeepSeek R1 investment thesis for a single stock."""
    symbol = symbol.upper().strip()
    user_id = req.client.host if req and req.client else "anonymous"

    stock, info, hist = await fetch_stock_data(symbol)
    stock_data = build_stock_response(symbol, stock, info, hist)
    news = get_latest_news(symbol)
    thesis = await ai_service.generate_investment_thesis(stock_data, news, user_id=user_id)

    return {"success": True, "symbol": symbol, "thesis": thesis, "timestamp": datetime.now().isoformat()}


@app.post("/api/ai/question")
async def ask_ai_question(request: dict, req: Request = None):
    """Ask any investment question; optionally grounded in a specific stock."""
    question = request.get("question")
    symbol = request.get("symbol")
    user_id = req.client.host if req and req.client else "anonymous"

    if not question:
        return {"success": False, "error": "Question is required"}

    stock_data = None
    if symbol:
        try:
            stock, info, hist = await fetch_stock_data(symbol.upper().strip())
            stock_data = build_stock_response(symbol, stock, info, hist)
        except Exception:
            pass

    answer = await ai_service.answer_question(question, stock_data, user_id=user_id)
    return {"success": True, "question": question, "answer": answer, "timestamp": datetime.now().isoformat()}


@app.post("/api/ai/sentiment")
async def analyze_sentiment(request: dict, req: Request = None):
    """AI market sentiment analysis from recent news."""
    symbols = request.get("symbols", [])
    user_id = req.client.host if req and req.client else "anonymous"

    if not symbols:
        return {"success": False, "error": "Symbols required"}

    news_data = {sym: get_latest_news(sym, max_news=3) for sym in symbols}
    sentiment = await ai_service.get_market_sentiment(symbols, news_data, user_id=user_id)

    return {"success": True, "sentiment": sentiment, "timestamp": datetime.now().isoformat()}


@app.get("/api/market-indices")
async def get_market_indices(use_cache: bool = True):
    """Major market indices + commodities."""
    cache_key = "market:indices"
    if use_cache:
        cached = stock_cache.get(cache_key)
        if cached:
            return cached

    indices = {
        '^GSPC': 'S&P 500', '^IXIC': 'NASDAQ', '^DJI': 'DOW JONES',
        '^RUT': 'RUSSELL 2K', '^VIX': 'VIX', 'BTC-USD': 'Bitcoin',
        'GC=F': 'Gold', 'CL=F': 'Crude Oil',
    }

    async def _fetch(sym: str, name: str):
        try:
            await yf_limiter.wait_if_needed()
            loop = asyncio.get_event_loop()
            stock = await loop.run_in_executor(None, yf.Ticker, sym)
            hist = await loop.run_in_executor(None, lambda: stock.history(period="2d"))
            if hist is not None and len(hist) >= 2:
                cur = float(hist['Close'].iloc[-1])
                prev = float(hist['Close'].iloc[-2])
                chg = ((cur - prev) / prev) * 100 if prev else 0
                return {"name": name, "value": round(cur, 2), "change": round(chg, 2)}
        except Exception as e:
            logger.warning(f"Failed to fetch {sym}: {e}")
        return {"name": name, "value": 0.0, "change": 0.0}

    data = await asyncio.gather(*[_fetch(s, n) for s, n in indices.items()])

    if use_cache:
        stock_cache.set(cache_key, data)

    return data


@app.get("/api/trending")
async def get_trending(use_cache: bool = True):
    """Trending US + Indian stocks."""
    cache_key = "trending:stocks"
    if use_cache:
        cached = stock_cache.get(cache_key)
        if cached:
            return cached

    symbols = [
        'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'TSLA', 'NVDA', 'META',
        'RELIANCE.NS', 'TCS.NS', 'HDFCBANK.NS', 'INFY.NS', 'ICICIBANK.NS',
        'ITC.NS', 'SBIN.NS', 'BHARTIARTL.NS', 'WIPRO.NS', 'TATAMOTORS.NS',
    ]

    async def _fetch(sym: str):
        try:
            await yf_limiter.wait_if_needed()
            loop = asyncio.get_event_loop()
            stock = await loop.run_in_executor(None, yf.Ticker, sym)
            info = await loop.run_in_executor(None, lambda: stock.info or {})
            hist = await loop.run_in_executor(None, lambda: stock.history(period="5d"))
            if hist is not None and len(hist) > 0:
                cur = float(hist['Close'].iloc[-1])
                prev = float(hist['Close'].iloc[-2]) if len(hist) > 1 else cur
                chg = ((cur - prev) / prev * 100) if prev else 0
                dsym = normalize_indian_symbol(sym)
                return {
                    "symbol": dsym,
                    "original_symbol": sym,
                    "name": safe_get(info, 'longName', dsym),
                    "price": round(cur, 2),
                    "change": round(chg, 2),
                    "volume": safe_float(safe_get(info, 'volume', 0)),
                    "market_cap": safe_float(safe_get(info, 'marketCap', 0)),
                    "is_indian": is_indian_stock(sym),
                }
        except Exception as e:
            logger.error(f"Trending fetch error for {sym}: {e}")
        return None

    results = await asyncio.gather(*[_fetch(s) for s in symbols])
    data = {"trending": [r for r in results if r]}

    if use_cache:
        stock_cache.set(cache_key, data)

    return data


@app.get("/api/search/{query}")
async def search_stocks(query: str):
    """Simple local-DB stock symbol/name search (US + Indian)."""
    if len(query) < 2:
        return {"results": []}

    stock_db = {
        "AAPL": "Apple Inc.", "MSFT": "Microsoft Corporation",
        "GOOGL": "Alphabet Inc.", "AMZN": "Amazon.com Inc.",
        "TSLA": "Tesla Inc.", "NVDA": "NVIDIA Corporation",
        "META": "Meta Platforms Inc.", "JPM": "JPMorgan Chase & Co.",
        "V": "Visa Inc.", "JNJ": "Johnson & Johnson",
        "WMT": "Walmart Inc.", "PG": "Procter & Gamble Co.",
        "DIS": "The Walt Disney Company", "NFLX": "Netflix Inc.",
        "ADBE": "Adobe Inc.", "PYPL": "PayPal Holdings Inc.",
        "INTC": "Intel Corporation", "CSCO": "Cisco Systems Inc.",
        "PFE": "Pfizer Inc.", "XOM": "Exxon Mobil Corporation",
        "BAC": "Bank of America Corp", "KO": "The Coca-Cola Company",
        "PEP": "PepsiCo Inc.", "NKE": "Nike Inc.",
        "RELIANCE.NS": "Reliance Industries Ltd",
        "TCS.NS": "Tata Consultancy Services Ltd",
        "HDFCBANK.NS": "HDFC Bank Ltd",
        "INFY.NS": "Infosys Ltd",
        "ICICIBANK.NS": "ICICI Bank Ltd",
        "ITC.NS": "ITC Ltd",
        "KOTAKBANK.NS": "Kotak Mahindra Bank Ltd",
        "SBIN.NS": "State Bank of India",
        "BHARTIARTL.NS": "Bharti Airtel Ltd",
        "DMART.NS": "Avenue Supermarts Ltd",
        "WIPRO.NS": "Wipro Ltd",
        "TECHM.NS": "Tech Mahindra Ltd",
        "TATAMOTORS.NS": "Tata Motors Ltd",
        "MARUTI.NS": "Maruti Suzuki India Ltd",
        "SUNPHARMA.NS": "Sun Pharmaceutical Industries Ltd",
        "HCLTECH.NS": "HCL Technologies Ltd",
        "LT.NS": "Larsen & Toubro Ltd",
        "AXISBANK.NS": "Axis Bank Ltd",
        "ONGC.NS": "Oil and Natural Gas Corporation Ltd",
        "NTPC.NS": "NTPC Ltd",
        "POWERGRID.NS": "Power Grid Corporation of India Ltd",
        "ULTRACEMCO.NS": "UltraTech Cement Ltd",
        "BAJFINANCE.NS": "Bajaj Finance Ltd",
        "ADANIPORTS.NS": "Adani Ports and SEZ Ltd",
        "TITAN.NS": "Titan Company Ltd",
    }

    q = query.upper()
    results = []
    for sym, name in stock_db.items():
        dsym = normalize_indian_symbol(sym)
        if q in dsym or q in name.upper():
            results.append({
                "symbol": dsym,
                "original_symbol": sym,
                "name": name,
                "match_type": "symbol" if q in dsym else "name",
                "is_indian": is_indian_stock(sym),
            })

    results.sort(key=lambda x: (
        0 if x['match_type'] == 'symbol' and x['symbol'] == q else
        1 if x['match_type'] == 'symbol' else 2,
        x['symbol']
    ))

    return {"results": results[:15]}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True, log_level="info")
