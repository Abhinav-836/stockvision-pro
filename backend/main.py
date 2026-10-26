# backend/main.py — OPTIMIZED HYBRID ENGINE (Finnhub → Alpha Vantage → yFinance)

from fastapi import FastAPI, HTTPException, Request, status, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, validator, Field
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
import yfinance as yf
import numpy as np
import asyncio
import logging
from collections import OrderedDict, defaultdict
import time
import re
import os
import json
import random
import aiohttp
from dotenv import load_dotenv

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

load_dotenv()

# Fix yFinance cache on Render
try:
    yf.set_tz_cache_location("/tmp/yfinance_cache")
except Exception:
    pass

# Optional proxy for yFinance calls — set the YFINANCE_PROXY_URL env var to
# route yfinance's requests through a proxy (a paid rotating proxy such as
# ScraperAPI/Webshare/Bright Data, or a small proxy you run yourself on a
# non-datacenter IP). This exists because Yahoo IP-blocks datacenter ranges
# (Render, AWS, Railway, Heroku...) at the network level — no header or
# retry change fixes that, only calling from a different IP does. Format:
# "http://user:pass@host:port" (or "http://host:port" if your proxy has no
# auth). Completely inert — yfinance behaves exactly as before — when the
# env var is unset, so this is safe to deploy even before you have a proxy.
YFINANCE_PROXY_URL = os.getenv("YFINANCE_PROXY_URL")
if YFINANCE_PROXY_URL:
    try:
        yf.set_config(proxy=YFINANCE_PROXY_URL)
        logger.info("yFinance configured to route through YFINANCE_PROXY_URL")
    except AttributeError:
        # Older yfinance builds don't have set_config(); upgrade yfinance
        # (pip install -U yfinance) to use this env var.
        logger.warning(
            "Installed yfinance version has no yf.set_config() — "
            "YFINANCE_PROXY_URL was set but is being ignored. "
            "Upgrade yfinance to enable the proxy."
        )

# Import finnhub with fallback
try:
    import finnhub
    FINNHUB_AVAILABLE = True
except ImportError:
    FINNHUB_AVAILABLE = False
    logger.warning("finnhub-python not installed. Finnhub features disabled.")

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


def _redact_secrets(text) -> str:
    """Remove API keys from text before it's logged.

    FIXED: Alpha Vantage echoes your key back in its rate-limit message
    ("We have detected your API key as XXXX..."), and those messages were
    logged verbatim — so the key ended up in Render's logs and in every log
    file shared for debugging.
    """
    text = str(text)
    for env_name in ("ALPHA_VANTAGE_API_KEY", "FINNHUB_API_KEY", "OPENROUTER_API_KEY"):
        secret = os.getenv(env_name)
        if secret and len(secret) >= 6:
            text = text.replace(secret, "***")
    return text


def _av_number(value) -> Optional[float]:
    """Parse an Alpha Vantage numeric field.

    AV returns every number as a string and uses the literal strings
    "None", "-" or "" for missing values; percentages sometimes carry a
    trailing "%". Returns None for anything that isn't a real number.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    text = str(value).replace("%", "").strip()
    if text in ("", "None", "-", "N/A", "null"):
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    return number if number == number else None  # drop NaN


# ============= NSE DIRECT PROVIDER (Indian equities) =============

class NSEDataProvider:
    """
    Direct client for NSE India's own public API (the same one
    nseindia.com's website calls) — no API key needed.

    WHY THIS EXISTS: Finnhub's free tier does not cover NSE/BSE symbols
    at all, and Alpha Vantage's India coverage is unreliable. That left
    yFinance as the ONLY data source anywhere in this app for Indian
    stocks (.NS/.BO) — so when Yahoo's IP-reputation block hits a shared
    host like Render, Indian stocks don't degrade to a slower tier, they
    just stop working entirely. NSE's endpoint is a completely different
    host than Yahoo, so a Yahoo-side block has zero effect on it.

    NSE has its own bot defenses — it 401s any request that doesn't look
    like it came from a real browser session — so every call here goes
    through a cookie-bootstrapped session with browser-like headers
    instead of a bare GET. NSE's free API only has price/trade data and a
    few identity fields, NOT valuation ratios (P/E aside), so this is
    layered in ahead of Finnhub/Alpha Vantage/yFinance for quotes and
    historical prices, but company_info still falls through to the other
    tiers for anything NSE doesn't have (ROE, debt-to-equity, EPS...).
    """

    BASE = "https://www.nseindia.com"
    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        # FIXED: advertised "br" (Brotli) but the Brotli package was never
        # installed, so NSE answered compressed responses aiohttp couldn't
        # decode — every NSE historical call failed with "Can not decode
        # content-encoding: brotli (br)" (seen in production logs) and
        # Indian charts silently fell back to yFinance. Only encodings
        # aiohttp can always decode are advertised now (Brotli is also in
        # requirements.txt as a safety net).
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive",
        "Referer": "https://www.nseindia.com/",
    }

    def __init__(self):
        self._session: Optional[aiohttp.ClientSession] = None
        self._cookies_ts = 0.0
        self._cookie_ttl = 240  # NSE's session cookies expire quickly
        self._lock = asyncio.Lock()
        self.calls = 0
        self.success = 0
        # FIXED: production logs showed NSE answering Render with HTTP 403
        # (quote) and an HTML block page instead of JSON (historical) —
        # NSE's Akamai bot protection rejects datacenter IPs outright, the
        # same way Yahoo does. Requests can now go through a proxy:
        # NSE_PROXY_URL if set, otherwise the same YFINANCE_PROXY_URL that
        # already gets yFinance past Yahoo's block.
        self.proxy = os.getenv("NSE_PROXY_URL") or os.getenv("YFINANCE_PROXY_URL") or None
        # Circuit breaker: when NSE is blocking us, every Indian lookup was
        # paying ~2s of doomed NSE round-trips before falling back to
        # yFinance. After 3 consecutive blocks, skip NSE for 10 minutes.
        self._consecutive_blocks = 0
        self._blocked_until = 0.0

    def is_blocked(self) -> bool:
        return time.time() < self._blocked_until

    def _record_block(self, reason: str):
        self._consecutive_blocks += 1
        self._cookies_ts = 0.0  # force a fresh cookie bootstrap next time
        if self._consecutive_blocks >= 3:
            self._blocked_until = time.time() + 600
            logger.warning(
                f"NSE blocked {self._consecutive_blocks} times in a row ({reason}) — "
                f"skipping NSE for 10 minutes, Indian data will come from yFinance"
            )

    def _record_ok(self):
        self._consecutive_blocks = 0
        self._blocked_until = 0.0

    async def _get_json(self, session: aiohttp.ClientSession, url: str, timeout: int, label: str):
        """GET a JSON endpoint; returns parsed JSON or None. NSE serves an
        HTML bot-check page (HTTP 200) when it blocks a client, which used
        to surface as a confusing "JSONDecodeError: Expecting value"."""
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=timeout), proxy=self.proxy) as resp:
            if resp.status != 200:
                logger.warning(f"NSE {label} HTTP {resp.status}")
                if resp.status in (401, 403):
                    self._record_block(f"HTTP {resp.status}")
                return None
            body = await resp.text()
        try:
            data = json.loads(body)
        except ValueError:
            logger.warning(f"NSE {label} returned non-JSON (bot-check page) — treating as blocked")
            self._record_block("non-JSON response")
            return None
        self._record_ok()
        return data

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(headers=self.HEADERS)
        return self._session

    async def _ensure_cookies(self):
        """Visit the NSE homepage first to pick up session cookies — the
        quote/historical endpoints 401 without them."""
        if time.time() - self._cookies_ts < self._cookie_ttl:
            return
        async with self._lock:
            if time.time() - self._cookies_ts < self._cookie_ttl:
                return
            session = await self._get_session()
            try:
                async with session.get(self.BASE, timeout=aiohttp.ClientTimeout(total=8), proxy=self.proxy) as resp:
                    await resp.read()
                self._cookies_ts = time.time()
            except Exception as e:
                logger.warning(f"NSE cookie bootstrap failed: {type(e).__name__}: {e}")

    async def get_quote(self, symbol: str) -> Optional[Dict]:
        """symbol WITHOUT the .NS/.BO suffix, e.g. 'RELIANCE'."""
        if self.is_blocked():
            return None
        try:
            await self._ensure_cookies()
            session = await self._get_session()
            self.calls += 1
            url = f"{self.BASE}/api/quote-equity?symbol={symbol}"
            # FIXED: non-200s used to return None silently, so a
            # blocked/expired NSE session was invisible in the logs.
            data = await self._get_json(session, url, 8, f"quote for {symbol}")
            if not data:
                return None

            price_info = data.get("priceInfo", {}) or {}
            last_price = price_info.get("lastPrice")
            if last_price is None:
                return None
            prev_close = price_info.get("previousClose", last_price) or last_price
            change = price_info.get("change")
            pchange = price_info.get("pChange")
            hi_lo = price_info.get("intraDayHighLow", {}) or {}
            trade_info = (data.get("marketDeptOrderBook", {}) or {}).get("tradeInfo", {}) or {}

            self.success += 1
            return {
                "price": float(last_price),
                "change": float(change) if change is not None else round(last_price - prev_close, 2),
                "change_percent": float(pchange) if pchange is not None else 0.0,
                "volume": int(trade_info.get("totalTradedVolume", 0) or 0),
                "previous_close": float(prev_close),
                "open": float(price_info.get("open", last_price) or last_price),
                "high": float(hi_lo.get("max", last_price) or last_price),
                "low": float(hi_lo.get("min", last_price) or last_price),
                "source": "NSE",
                "latency": "delayed"
            }
        except Exception as e:
            logger.warning(f"NSE quote error for {symbol}: {type(e).__name__}: {e}")
            return None

    async def get_historical(self, symbol: str, period: str = "1mo") -> Optional[List[Dict]]:
        """NSE's historical endpoint wants an explicit date range rather
        than a period string, so period is translated to a day count."""
        days_map = {"1d": 3, "5d": 7, "1mo": 32, "3mo": 95, "6mo": 190,
                    "1y": 370, "2y": 740, "5y": 1850}
        days = days_map.get(period, 32)
        end = datetime.now()
        start = end - timedelta(days=days)
        if self.is_blocked():
            return None
        try:
            await self._ensure_cookies()
            session = await self._get_session()
            self.calls += 1
            url = (
                f"{self.BASE}/api/historical/cm/equity?symbol={symbol}"
                f"&series=[%22EQ%22]&from={start.strftime('%d-%m-%Y')}&to={end.strftime('%d-%m-%Y')}"
            )
            data = await self._get_json(session, url, 10, f"historical for {symbol}")
            if not data:
                return None

            rows = data.get("data", [])
            if not rows:
                return None
            result = []
            for row in reversed(rows):  # NSE returns newest-first
                try:
                    result.append({
                        "date": datetime.strptime(row["CH_TIMESTAMP"], "%Y-%m-%d").isoformat(),
                        "price": round(float(row["CH_CLOSING_PRICE"]), 2),
                        "open": round(float(row["CH_OPENING_PRICE"]), 2),
                        "high": round(float(row["CH_TRADE_HIGH_PRICE"]), 2),
                        "low": round(float(row["CH_TRADE_LOW_PRICE"]), 2),
                        "volume": int(row.get("CH_TOT_TRADED_QTY", 0) or 0)
                    })
                except (KeyError, ValueError, TypeError):
                    continue
            if not result:
                return None
            self.success += 1
            return result
        except Exception as e:
            logger.warning(f"NSE historical error for {symbol}: {type(e).__name__}: {e}")
            return None

    async def get_company_info(self, symbol: str) -> Optional[Dict]:
        """NSE's quote payload has identity/trade fields and P/E, but not
        ROE/debt-to-equity/EPS etc — those still come from AV/yFinance.
        Returned in yFinance's camelCase schema so it merges cleanly."""
        if self.is_blocked():
            return None
        try:
            await self._ensure_cookies()
            session = await self._get_session()
            url = f"{self.BASE}/api/quote-equity?symbol={symbol}"
            data = await self._get_json(session, url, 8, f"company info for {symbol}")
            if not data:
                return None

            info_block = data.get("info", {}) or {}
            metadata = data.get("metadata", {}) or {}
            price_info = data.get("priceInfo", {}) or {}
            week = price_info.get("weekHighLow", {}) or {}

            result: Dict = {}
            if info_block.get("companyName"):
                result["longName"] = info_block["companyName"]
                result["shortName"] = info_block["companyName"]
            if info_block.get("industry"):
                result["sector"] = info_block["industry"]
            if metadata.get("pdSymbolPe") not in (None, "", "-"):
                try:
                    result["trailingPE"] = float(metadata["pdSymbolPe"])
                except (ValueError, TypeError):
                    pass
            if week.get("max") is not None:
                result["fiftyTwoWeekHigh"] = float(week["max"])
            if week.get("min") is not None:
                result["fiftyTwoWeekLow"] = float(week["min"])
            return result if result else None
        except Exception as e:
            logger.warning(f"NSE company info error for {symbol}: {type(e).__name__}: {e}")
            return None


# ============= OPTIMIZED HYBRID DATA ENGINE =============

class HybridDataEngine:
    """
    OPTIMIZED Hybrid data provider with cascading fallback:
    Finnhub (fastest real-time) → Alpha Vantage (best fundamentals) → yFinance (ultimate fallback)
    """
    
    def __init__(self):
        # Finnhub (Priority 1 - Fastest real-time)
        self.fh_api_key = os.getenv("FINNHUB_API_KEY")
        self.fh_enabled = bool(self.fh_api_key) and FINNHUB_AVAILABLE
        self.fh_client = finnhub.Client(api_key=self.fh_api_key) if self.fh_enabled else None
        self.fh_calls = 0
        self.fh_success = 0
        self.fh_calls_minute = []
        # FIXED: Finnhub's free tier does not include the historical
        # candles endpoint (stock_candles) — it returns a permanent
        # 403 "You don't have access to this resource." Once we see
        # that, stop wasting a network round-trip on it for the rest
        # of this process's lifetime; quote/company-profile calls are
        # unaffected and keep working normally on the free tier.
        self.fh_historical_available = True
        # Last real value seen per index symbol, used when Finnhub can't
        # cover a symbol instead of burning yFinance's shared rate-limit
        # budget on something that reliably fails anyway.
        self._last_good_indices: Dict[str, Dict] = {}
        # Tracks in-flight get_historical() calls so concurrent identical
        # requests (see get_historical() docstring) share one fetch
        # instead of each independently burning API quota.
        self._inflight_historical: Dict[str, asyncio.Task] = {}

        # Alpha Vantage (Priority 2 - Best fundamentals)
        self.av_api_key = os.getenv("ALPHA_VANTAGE_API_KEY")
        self.av_base_url = "https://www.alphavantage.co/query"
        self.av_enabled = bool(self.av_api_key)
        self.av_calls = 0
        self.av_success = 0
        self.av_calls_minute = []
        self.av_calls_day = []
        self.av_day_reset = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        # FIXED: Alpha Vantage's actual free-tier daily limit is 25
        # requests/day, not 500. The old 500 cap meant the app kept
        # firing requests at AV long after the real quota was gone,
        # burning time on calls that were guaranteed to be rejected.
        self.av_daily_limit = int(os.getenv("ALPHA_VANTAGE_DAILY_LIMIT", 25))
        # AV functions this key isn't entitled to. Production logs showed
        # OVERVIEW coming back as "This is a premium endpoint" on the free
        # key — retrying it on every lookup burned 1 of 25 daily calls each
        # time for a guaranteed rejection. Once AV says a function is
        # premium, it's skipped for the rest of the process.
        self.av_premium_functions: set = set()

        # Cache (optimized with shorter TTL for real-time)
        self.cache = {}
        self.quote_cache_ttl = 30  # 30 seconds for real-time quotes
        self.historical_cache_ttl = 300  # 5 minutes for historical
        
        # Stats
        self.yf_calls = 0
        self.yf_success = 0

        # NSE direct provider — the only real free source for Indian
        # equities (.NS/.BO). See NSEDataProvider docstring for why.
        self.nse_provider = NSEDataProvider()
        
        logger.info(f"🚀 Hybrid Engine initialized: FH={self.fh_enabled}, AV={self.av_enabled}")
    
    # ========================================================================
    # FINNHUB METHODS (Priority 1 - Fastest)
    # ========================================================================
    
    def _can_call_fh(self) -> bool:
        """Check Finnhub rate limit (60/min free)"""
        now = time.time()
        self.fh_calls_minute = [t for t in self.fh_calls_minute if now - t < 60]
        return len(self.fh_calls_minute) < 60
    
    def _record_fh_call(self):
        self.fh_calls += 1
        self.fh_calls_minute.append(time.time())
    
    async def _fetch_fh_quote(self, symbol: str) -> Optional[Dict]:
        """Fetch quote from Finnhub - FASTEST real-time data"""
        if not self.fh_enabled or not self._can_call_fh():
            return None
        
        try:
            loop = asyncio.get_event_loop()
            quote = await loop.run_in_executor(None, self.fh_client.quote, symbol)
            self._record_fh_call()
            
            if quote and quote.get('c', 0) > 0:
                self.fh_success += 1
                return {
                    "price": float(quote.get('c', 0)),
                    "change": round(float(quote.get('c', 0) - quote.get('pc', 0)), 2),
                    "change_percent": round(float(quote.get('dp', 0)), 2),
                    "volume": int(quote.get('v', 0)),
                    "previous_close": float(quote.get('pc', 0)),
                    "open": float(quote.get('o', 0)),
                    "high": float(quote.get('h', 0)),
                    "low": float(quote.get('l', 0)),
                    "source": "Finnhub",
                    "latency": "real-time"
                }
        except Exception as e:
            logger.warning(f"Finnhub quote error for {symbol}: {type(e).__name__}: {e}")
        return None
    
    async def _fetch_fh_historical(self, symbol: str, period: str = "1mo") -> Optional[List[Dict]]:
        """Fetch historical from Finnhub"""
        # Finnhub's free tier permanently returns 403 on /stock/candle
        # (confirmed repeatedly in production logs) — it's a plan
        # restriction, not a transient error, so retrying it on every
        # single chart/quote request just wastes a network round-trip and
        # fills the logs with noise. self.fh_historical_available starts
        # True and flips to False the first time we see a 403 (below),
        # so we stop trying for the rest of this process's lifetime
        # without needing any manual configuration.
        if not self.fh_historical_available:
            return None
        if not self.fh_enabled or not self._can_call_fh():
            return None
        
        try:
            # Map period to resolution
            end = datetime.now()
            if period == "1d":
                start = end - timedelta(days=2)
                resolution = "5"
            elif period == "5d":
                start = end - timedelta(days=7)
                resolution = "15"
            elif period == "1mo":
                start = end - timedelta(days=30)
                resolution = "60"
            elif period == "3mo":
                start = end - timedelta(days=90)
                resolution = "D"
            elif period == "6mo":
                start = end - timedelta(days=180)
                resolution = "D"
            else:  # 1y
                start = end - timedelta(days=365)
                resolution = "D"
            
            start_ts = int(start.timestamp())
            end_ts = int(end.timestamp())
            
            loop = asyncio.get_event_loop()
            data = await loop.run_in_executor(
                None,
                self.fh_client.stock_candles,
                symbol, resolution, start_ts, end_ts
            )
            self._record_fh_call()
            
            if data and data.get('s') == 'ok' and data.get('c'):
                result = []
                for i in range(len(data['t'])):
                    try:
                        result.append({
                            "date": datetime.fromtimestamp(data['t'][i]).isoformat(),
                            "price": float(data['c'][i]),
                            "open": float(data['o'][i]),
                            "high": float(data['h'][i]),
                            "low": float(data['l'][i]),
                            "volume": int(data['v'][i])
                        })
                    except:
                        continue
                
                if result:
                    self.fh_success += 1
                    return result
        except Exception as e:
            # A 403 here means the plan restriction, not a transient
            # issue — stop retrying this for the rest of the process's
            # lifetime instead of hitting it (and logging it) again on
            # every future chart/historical request.
            if "403" in str(e):
                if self.fh_historical_available:
                    logger.warning(
                        f"Finnhub historical returned 403 (plan restriction) — "
                        f"disabling Finnhub historical for the rest of this session"
                    )
                self.fh_historical_available = False
            logger.warning(f"Finnhub historical error for {symbol}: {type(e).__name__}: {e}")
        return None
    
    async def _fetch_fh_company_info(self, symbol: str) -> Optional[Dict]:
        """Fetch company profile from Finnhub"""
        if not self.fh_enabled or not self._can_call_fh():
            return None
        
        try:
            loop = asyncio.get_event_loop()
            # FIXED: company_profile2(**params) only accepts keyword
            # arguments — passing symbol positionally (the old code) threw
            # "takes 1 positional argument but 2 were given" on every
            # single call, silently killing Finnhub's company info tier
            # regardless of plan/API key validity.
            profile = await asyncio.wait_for(
                loop.run_in_executor(None, lambda: self.fh_client.company_profile2(symbol=symbol)),
                timeout=8
            )
            self._record_fh_call()
            
            if profile:
                self.fh_success += 1
                # FIXED: Finnhub returns marketCapitalization in MILLIONS
                # of the reporting currency (their documented convention),
                # not raw dollars — unlike Alpha Vantage's
                # MarketCapitalization field, which already is raw
                # dollars. Storing it unconverted made every FH-sourced
                # market cap display 1,000,000x too small (e.g. AAPL's
                # true ~$4.6T showing as "$4.60M").
                raw_market_cap = profile.get('marketCapitalization', 0)
                return {
                    "company_name": profile.get('name'),
                    "sector": profile.get('finnhubIndustry'),
                    "market_cap": float(raw_market_cap) * 1_000_000,
                    "exchange": profile.get('exchange'),
                    "country": profile.get('country'),
                }
        except Exception as e:
            logger.warning(f"Finnhub company info error for {symbol}: {type(e).__name__}: {e}")
        return None
    
    # ========================================================================
    # ALPHA VANTAGE METHODS (Priority 2 - Best fundamentals)
    # ========================================================================
    
    def _can_call_av(self) -> bool:
        """Check Alpha Vantage rate limit (5/min, av_daily_limit/day).

        FIXED: the daily check was still hardcoded to `< 500` even after
        self.av_daily_limit was corrected to AV's real free-tier quota of
        25. The limit was never actually enforced — the app kept firing
        AV requests all day after the real quota was gone.
        """
        now = time.time()
        self.av_calls_minute = [t for t in self.av_calls_minute if now - t < 60]
        if len(self.av_calls_minute) >= 5:
            return False

        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        if today > self.av_day_reset:
            self.av_calls_day = []
            self.av_day_reset = today

        self.av_calls_day = [t for t in self.av_calls_day if t >= self.av_day_reset.timestamp()]
        return len(self.av_calls_day) < self.av_daily_limit
    
    def _note_av_rejection(self, function: str, message) -> None:
        """Handle an AV "Information" rejection: premium-only function,
        or the per-key daily limit."""
        text = str(message or "")
        if "premium" in text.lower():
            if function not in self.av_premium_functions:
                self.av_premium_functions.add(function)
                logger.warning(f"Alpha Vantage {function} is premium-only for this key — not calling it again this session")
        self._note_av_daily_limit(text)

    def _note_av_daily_limit(self, message) -> None:
        """AV's own counter is per KEY, not per server process: calls from
        local testing, other projects or earlier deploys today all count.
        So the in-process counter can say "3 of 25 used" while AV has
        already cut the key off. When AV reports its daily limit, stop
        calling it until midnight instead of burning a request (and a
        5s-per-minute slot) on every lookup for the rest of the day."""
        if message and "per day" in str(message):
            self.av_calls_day = [time.time()] * self.av_daily_limit
            logger.warning("Alpha Vantage daily quota exhausted for this key — pausing AV until midnight")

    def _record_av_call(self):
        now = time.time()
        self.av_calls += 1
        self.av_calls_minute.append(now)
        self.av_calls_day.append(now)
    
    async def _fetch_av_quote(self, symbol: str) -> Optional[Dict]:
        """Fetch quote from Alpha Vantage"""
        if not self.av_enabled or not self._can_call_av():
            return None
        
        try:
            params = {
                "function": "GLOBAL_QUOTE",
                "symbol": symbol,
                "apikey": self.av_api_key
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(self.av_base_url, params=params, timeout=8) as response:
                    data = await response.json()
                    self._record_av_call()
                    
                    quote = data.get("Global Quote", {})
                    if quote and quote.get("05. price"):
                        price = float(quote.get("05. price", 0))
                        if price > 0:
                            self.av_success += 1
                            return {
                                "price": price,
                                "change": round(float(quote.get("09. change", 0)), 2),
                                "change_percent": float(quote.get("10. change percent", "0%").replace("%", "")),
                                "volume": int(quote.get("06. volume", 0)),
                                "previous_close": float(quote.get("08. previous close", price)),
                                "open": float(quote.get("02. open", price)),
                                "high": float(quote.get("03. high", price)),
                                "low": float(quote.get("04. low", price)),
                                "source": "Alpha Vantage",
                                "latency": "slightly delayed"
                            }
                    # AV returns rate-limit/error messages as HTTP 200 with
                    # a message field instead of an actual quote — these
                    # were previously silent. Surface them.
                    if any(k in data for k in ("Error Message", "Note", "Information")):
                        logger.warning(f"Alpha Vantage quote rejected for {symbol}: {_redact_secrets(data)}")
        except Exception as e:
            logger.warning(f"Alpha Vantage quote error for {symbol}: {type(e).__name__}: {e}")
        return None
    
    # Calendar days each chart period covers. Alpha Vantage's free
    # TIME_SERIES_DAILY only serves outputsize=compact (latest 100 trading
    # days ≈ 140 calendar days); outputsize=full is a premium feature.
    PERIOD_DAYS = {"1d": 1, "5d": 7, "1mo": 31, "3mo": 92, "6mo": 183, "1y": 366, "2y": 731, "5y": 1827}
    AV_COMPACT_MAX_DAYS = 140

    def av_covers_period(self, period: str) -> bool:
        return self.PERIOD_DAYS.get(period, 31) <= self.AV_COMPACT_MAX_DAYS

    async def _fetch_av_historical(self, symbol: str, period: str = "1mo") -> Optional[List[Dict]]:
        """Fetch historical from Alpha Vantage.

        FIXED (3 bugs):
        1. 3mo/6mo/1y requested outputsize=full, which is premium-only on
           AV's free tier. Every one of those requests came back as an
           "Information" rejection — guaranteed to fail, but still burning
           one of the 25 daily calls. Always compact now.
        2. Rows were returned NEWEST-FIRST (sorted reverse=True). Every
           other tier returns oldest-first, and everything downstream
           assumes it: hist['Close'].iloc[-1] became the OLDEST close, so
           RSI/MACD/SMA trend, the price fallback and volatility were all
           computed backwards whenever AV served the data.
        3. The period was ignored — "1mo" returned 100 trading days
           (~5 months), so the 1M chart showed five months of data.
        """
        if not self.av_enabled or "TIME_SERIES_DAILY" in self.av_premium_functions or not self._can_call_av():
            return None

        try:
            params = {
                "function": "TIME_SERIES_DAILY",
                "symbol": symbol,
                "outputsize": "compact",
                "apikey": self.av_api_key
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(self.av_base_url, params=params, timeout=12) as response:
                    data = await response.json()
                    self._record_av_call()
                    
                    if "Error Message" in data:
                        logger.warning(f"Alpha Vantage historical rejected for {symbol}: {_redact_secrets(data.get('Error Message'))}")
                        return None
                    if "Note" in data:
                        logger.warning(f"Alpha Vantage historical rate-limited for {symbol}: {_redact_secrets(data.get('Note'))}")
                        return None
                    if "Information" in data:
                        self._note_av_rejection("TIME_SERIES_DAILY", data.get('Information'))
                        logger.warning(f"Alpha Vantage historical rejected for {symbol}: {_redact_secrets(data.get('Information'))}")
                        return None
                    
                    time_series = data.get("Time Series (Daily)", {})
                    if time_series:
                        cutoff = (datetime.now() - timedelta(days=self.PERIOD_DAYS.get(period, 31))).strftime("%Y-%m-%d")
                        result = []
                        # Oldest-first, like every other tier.
                        for date, values in sorted(time_series.items()):
                            if date < cutoff:
                                continue
                            try:
                                result.append({
                                    "date": date,
                                    "price": float(values.get("4. close", 0)),
                                    "open": float(values.get("1. open", 0)),
                                    "high": float(values.get("2. high", 0)),
                                    "low": float(values.get("3. low", 0)),
                                    "volume": int(values.get("5. volume", 0))
                                })
                            except:
                                continue
                        
                        if result:
                            self.av_success += 1
                            return result
        except Exception as e:
            logger.warning(f"Alpha Vantage historical error for {symbol}: {type(e).__name__}: {e}")
        return None
    
    async def _fetch_av_company_info(self, symbol: str) -> Optional[Dict]:
        """Fetch company overview from Alpha Vantage (BEST FUNDAMENTALS)"""
        if not self.av_enabled or "OVERVIEW" in self.av_premium_functions or not self._can_call_av():
            return None
        
        try:
            params = {
                "function": "OVERVIEW",
                "symbol": symbol,
                "apikey": self.av_api_key
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(self.av_base_url, params=params, timeout=8) as response:
                    data = await response.json()
                    self._record_av_call()
                    
                    if isinstance(data, dict) and "Information" in data:
                        self._note_av_rejection("OVERVIEW", data.get("Information"))
                        logger.warning(f"Alpha Vantage overview rejected for {symbol}: {_redact_secrets(data.get('Information'))}")
                        return None
                    if data and "Symbol" in data:
                        self.av_success += 1
                        # NOTE: Alpha Vantage's OVERVIEW endpoint has no
                        # "DebtToEquity" field at all — it never existed in
                        # their schema. Also "RevenueGrowth" isn't a real AV
                        # field either; the correct key is
                        # "QuarterlyRevenueGrowthYOY".
                        #
                        # FIXED: AV sends the literal STRING "None" (or "-")
                        # for any field it doesn't have — e.g. PERatio for
                        # every loss-making company, DividendYield for
                        # non-payers. float("None") raised ValueError, the
                        # except below swallowed it, and the ENTIRE AV
                        # result was thrown away (after spending one of the
                        # 25 daily calls). Every field is parsed with
                        # _av_number() now and simply omitted when missing.
                        #
                        # FIXED: QuarterlyRevenueGrowthYOY is a decimal
                        # (0.061 = 6.1%), the same unit yFinance uses. It
                        # used to be multiplied by 100 here, and then
                        # analyze_growth() multiplied by 100 AGAIN — so a
                        # 6.1% grower was displayed as 610% growth.
                        result = {
                            "symbol": data.get("Symbol"),
                            "company_name": data.get("Name"),
                            "sector": data.get("Sector"),
                            "industry": data.get("Industry"),
                        }
                        numeric_fields = {
                            "market_cap": "MarketCapitalization",
                            "pe_ratio": "PERatio",
                            "pb_ratio": "PriceToBookRatio",
                            "roe": "ReturnOnEquityTTM",
                            "roa": "ReturnOnAssetsTTM",
                            "dividend_yield": "DividendYield",
                            "eps": "EPS",
                            "debt_to_equity": "DebtToEquity",
                            "revenue_growth": "QuarterlyRevenueGrowthYOY",
                        }
                        for out_key, av_key in numeric_fields.items():
                            value = _av_number(data.get(av_key))
                            if value is not None:
                                result[out_key] = value
                        return result
        except Exception as e:
            logger.warning(f"Alpha Vantage company info error for {symbol}: {type(e).__name__}: {e}")
        return None
    
    # ========================================================================
    # YFINANCE METHODS (Priority 3 - Ultimate fallback)
    # ========================================================================
    
    async def _fetch_yf_quote(self, symbol: str) -> Optional[Dict]:
        """Fetch quote from yFinance (fallback)"""
        if yf_rate_limiter.is_blocked():
            return None
        try:
            # FIXED: this call previously bypassed yf_rate_limiter entirely,
            # so it could fire concurrently with other yfinance calls
            # (historical, company info, chart endpoint) and trip Yahoo's
            # anti-scraping throttling — causing intermittent failures that
            # made the app fall back to fake demo data.
            await yf_rate_limiter.acquire()
            loop = asyncio.get_event_loop()
            # FIXED: yfinance calls have no built-in timeout (unlike
            # Finnhub's 10s and Alpha Vantage's aiohttp timeout=8/12).
            # Wrapped in wait_for so a stalled connection can no longer
            # hang the whole cascading-fallback chain past the frontend's
            # 30s request timeout.
            stock = await asyncio.wait_for(loop.run_in_executor(None, yf.Ticker, symbol), timeout=8)
            info = await asyncio.wait_for(loop.run_in_executor(None, lambda: stock.info or {}), timeout=8)
            self.yf_calls += 1
            
            price = info.get('currentPrice') or info.get('regularMarketPrice') or info.get('previousClose')
            if price:
                self.yf_success += 1
                yf_rate_limiter.record_success()
                return {
                    "price": float(price),
                    "change": float(info.get('regularMarketChange', 0)),
                    "change_percent": float(info.get('regularMarketChangePercent', 0)),
                    "volume": int(info.get('volume', 0)),
                    "previous_close": float(info.get('previousClose', price)),
                    "open": float(info.get('open', price)),
                    "high": float(info.get('dayHigh', price)),
                    "low": float(info.get('dayLow', price)),
                    "source": "yFinance",
                    "latency": "delayed"
                }
        except Exception as e:
            yf_rate_limiter.record_failure()
            logger.warning(f"yFinance quote error for {symbol}: {type(e).__name__}: {e}")
        return None
    
    async def _fetch_yf_historical(self, symbol: str, period: str = "1mo", interval: str = "1d") -> Optional[List[Dict]]:
        """Fetch historical from yFinance (fallback)"""
        if yf_rate_limiter.is_blocked():
            return None
        try:
            await yf_rate_limiter.acquire()
            loop = asyncio.get_event_loop()
            stock = await asyncio.wait_for(loop.run_in_executor(None, yf.Ticker, symbol), timeout=8)
            hist = await asyncio.wait_for(
                loop.run_in_executor(None, lambda: stock.history(period=period, interval=interval)),
                timeout=10
            )
            self.yf_calls += 1
            
            if hist is not None and not hist.empty:
                self.yf_success += 1
                yf_rate_limiter.record_success()
                result = []
                for date, row in hist.iterrows():
                    result.append({
                        "date": date.isoformat(),
                        "price": round(float(row['Close']), 2),
                        "open": round(float(row['Open']), 2),
                        "high": round(float(row['High']), 2),
                        "low": round(float(row['Low']), 2),
                        "volume": int(row['Volume']) if 'Volume' in row else 0
                    })
                return result
        except Exception as e:
            yf_rate_limiter.record_failure()
            logger.warning(f"yFinance historical error for {symbol}: {type(e).__name__}: {e}")
        return None
    
    async def _fetch_yf_company_info(self, symbol: str) -> Optional[Dict]:
        """Fetch company info from yFinance (fallback).

        FIXED: this was the only yFinance call that ignored the circuit
        breaker — it neither checked is_blocked() nor recorded
        success/failure. While Yahoo was actively blocking the server it
        kept firing (and waiting out its 8s timeouts) on every lookup, and
        its failures never counted toward opening the breaker.
        """
        if yf_rate_limiter.is_blocked():
            return None
        try:
            await yf_rate_limiter.acquire()
            loop = asyncio.get_event_loop()
            stock = await asyncio.wait_for(loop.run_in_executor(None, yf.Ticker, symbol), timeout=8)
            info = await asyncio.wait_for(loop.run_in_executor(None, lambda: stock.info or {}), timeout=8)
            self.yf_calls += 1

            if info:
                self.yf_success += 1
                yf_rate_limiter.record_success()
                return info
            yf_rate_limiter.record_failure()
        except Exception as e:
            yf_rate_limiter.record_failure()
            logger.warning(f"yFinance company info error for {symbol}: {type(e).__name__}: {e}")
        return None
    
    # ========================================================================
    # PUBLIC METHODS WITH CASCADING FALLBACK
    # ========================================================================
    
    async def get_quote(self, symbol: str) -> Optional[Dict]:
        """Get real-time quote with cascading fallback.

        FIXED: Alpha Vantage's free tier is a strict 25 requests/day — a
        genuinely scarce resource. It used to be tried here for every
        single quote, even though Finnhub already handles quotes
        reliably on its own. Every AV call spent on a quote Finnhub could
        already serve is one less call available for company fundamentals
        (P/E, P/B, ROE, EPS, D/E...), which is the one thing AV provides
        that neither Finnhub nor a rate-limited yFinance reliably can.
        AV is no longer used for quotes — see get_company_info() for
        where its scarce budget is now reserved.
        """
        
        cache_key = f"quote:{symbol}"
        if cache_key in self.cache:
            cached, ts = self.cache[cache_key]
            if time.time() - ts < self.quote_cache_ttl:
                return cached

        # Indian equities: Finnhub's free tier doesn't recognize NSE/BSE
        # symbols at all, so trying it first for .NS/.BO just burns a
        # guaranteed-miss call. Go straight to NSE's own API instead.
        indian = is_indian_stock(symbol)
        if indian:
            nse_result = await self.nse_provider.get_quote(normalize_indian_symbol(symbol))
            if nse_result:
                self.cache[cache_key] = (nse_result, time.time())
                return nse_result
        
        # Priority 1: Finnhub (Fastest real-time)
        # FIXED: when NSE failed, Indian symbols used to fall through to
        # Finnhub too — which always 403s for .NS/.BO on the free plan (seen
        # in production logs), wasting a call from the 60/min budget.
        if not indian:
            result = await self._fetch_fh_quote(symbol)
            if result:
                self.cache[cache_key] = (result, time.time())
                return result
        
        # Priority 2: yFinance (fallback if Finnhub is down/plan-limited)
        result = await self._fetch_yf_quote(symbol)
        if result:
            self.cache[cache_key] = (result, time.time())
            return result
        
        return None
    
    async def get_historical(self, symbol: str, period: str = "1mo", interval: str = "1d") -> Optional[List[Dict]]:
        """Get historical data with cascading fallback.

        FIXED: the frontend fires the chart request and the main
        stock-analysis request in parallel (intentional, for speed), and
        both end up calling this with the same symbol/period/interval at
        nearly the same instant — before either one has finished and
        populated self.cache. That meant BOTH independently burned a
        separate Alpha Vantage call for identical data (confirmed in
        production logs: two "Alpha Vantage historical rejected"
        messages, 300ms apart, for the same symbol in the same page
        load) — needlessly doubling the burn rate against AV's strict
        25/day quota. Concurrent identical requests now share one
        in-flight fetch instead of each starting their own.
        """
        
        cache_key = f"hist:{symbol}:{period}:{interval}"
        if cache_key in self.cache:
            cached, ts = self.cache[cache_key]
            if time.time() - ts < self.historical_cache_ttl:
                return cached

        if cache_key in self._inflight_historical:
            return await self._inflight_historical[cache_key]

        task = asyncio.ensure_future(self._fetch_historical_uncached(symbol, period, interval, cache_key))
        self._inflight_historical[cache_key] = task
        try:
            return await task
        finally:
            self._inflight_historical.pop(cache_key, None)

    async def _fetch_historical_uncached(self, symbol: str, period: str, interval: str, cache_key: str) -> Optional[List[Dict]]:
        # Indian equities: same reasoning as get_quote() — Finnhub/AV
        # don't cover NSE/BSE, so try NSE's own historical endpoint first.
        if is_indian_stock(symbol):
            nse_result = await self.nse_provider.get_historical(normalize_indian_symbol(symbol), period)
            if nse_result:
                self.cache[cache_key] = (nse_result, time.time())
                return nse_result

        # Priority 1: Finnhub (Fastest) — not for NSE/BSE (free plan 403s)
        if not is_indian_stock(symbol):
            result = await self._fetch_fh_historical(symbol, period)
            if result:
                self.cache[cache_key] = (result, time.time())
                return result

        # Alpha Vantage only has free DAILY bars for the last ~100 trading
        # days, it doesn't cover NSE/BSE, and it has no intraday data for
        # the 1D/5D charts. Only spend one of its 25 daily calls when it
        # can actually answer the request; otherwise go to yFinance.
        av_useful = (
            not is_indian_stock(symbol)
            and interval == "1d"
            and period not in ("1d", "5d")
        )

        if av_useful and self.av_covers_period(period):
            # Priority 2: Alpha Vantage (fully covers this period)
            result = await self._fetch_av_historical(symbol, period)
            if result:
                self.cache[cache_key] = (result, time.time())
                return result

        # Priority 3: yFinance
        result = await self._fetch_yf_historical(symbol, period, interval)
        if result:
            self.cache[cache_key] = (result, time.time())
            return result

        if av_useful and not self.av_covers_period(period):
            # Last resort for long periods: AV's ~5 months is still real
            # data and far better than a synthetic chart.
            result = await self._fetch_av_historical(symbol, period)
            if result:
                self.cache[cache_key] = (result, time.time())
                return result

        return None
    
    async def get_company_info(self, symbol: str) -> Optional[Dict]:
        """Get company fundamentals, merging across tiers rather than
        stopping at the first success.

        NOTE: Alpha Vantage and Finnhub return snake_case field names
        (pe_ratio, market_cap, roe...), but everything downstream
        (financials.py's calculators, build_stock_response) expects
        yfinance's native camelCase schema (trailingPE, marketCap,
        returnOnEquity...). Results from those two tiers are normalized
        to that schema here — at the source — so every caller gets a
        consistent shape regardless of which tier actually served the
        data. yFinance's own result is already in the right schema.

        FIXED: this used to return as soon as ANY tier gave a non-empty
        result — but Finnhub's company_profile2 ALWAYS succeeds with only
        company_name/sector/market_cap/exchange/country and structurally
        never has P/E, P/B, ROE, EPS, D/E, average volume, or 52-week
        range at all. That "partial success" was permanently blocking
        yFinance — the only tier that actually has those fields — from
        ever being tried. Now every enabled tier is asked to fill in
        whatever's still missing, in priority order (Alpha Vantage's
        numbers win when available since they're generally the most
        accurate; Finnhub fills identity fields; yFinance fills whatever
        is still gap after both).
        """
        merged: Dict = {}
        key_fields = (
            "trailingPE", "priceToBook", "returnOnEquity", "trailingEps",
            "debtToEquity", "averageVolume", "fiftyTwoWeekHigh", "fiftyTwoWeekLow"
        )

        def still_missing() -> bool:
            return not all(merged.get(k) is not None for k in key_fields)

        # Priority 0: NSE direct (Indian equities only — identity fields,
        # P/E, and 52-week range; never has ROE/D-to-E/EPS, so the tiers
        # below still run to fill the rest).
        if is_indian_stock(symbol):
            nse_result = await self.nse_provider.get_company_info(normalize_indian_symbol(symbol))
            if nse_result:
                for k, v in nse_result.items():
                    merged.setdefault(k, v)

        # Priority 1: Alpha Vantage (best fundamentals when it's not rate-limited)
        # FIXED: skipped for Indian symbols — AV's OVERVIEW endpoint has no
        # NSE/BSE coverage, so "RELIANCE.NS" always came back empty while
        # still consuming one of the 25 free calls per day.
        if not is_indian_stock(symbol):
            av_result = await self._fetch_av_company_info(symbol)
            if av_result:
                for k, v in _map_av_fh_company_info_to_yf_schema(av_result).items():
                    merged.setdefault(k, v)

        # Priority 2: Finnhub (sector/market cap/exchange — never has
        # valuation ratios, but still worth asking for what it does have)
        # Skipped for NSE/BSE: the free plan 403s on .NS/.BO profiles.
        if (still_missing() or not merged) and not is_indian_stock(symbol):
            fh_result = await self._fetch_fh_company_info(symbol)
            if fh_result:
                for k, v in _map_av_fh_company_info_to_yf_schema(fh_result).items():
                    merged.setdefault(k, v)

        # Priority 3: yFinance — the only tier with the full set of
        # valuation ratios. Called whenever anything is still missing,
        # not only when the first two tiers returned nothing at all.
        if still_missing() or not merged:
            yf_result = await self._fetch_yf_company_info(symbol)
            if yf_result:
                for k, v in yf_result.items():
                    merged.setdefault(k, v)

        return merged if merged else None

    async def get_company_identity(self, symbol: str) -> Dict:
        """Name + market cap only, for lightweight lists (trending).

        Uses Finnhub's profile (60 calls/min) and never Alpha Vantage or
        yFinance — the trending endpoint used to call get_company_info()
        for 7 symbols, spending up to 7 of Alpha Vantage's 25 daily calls
        on a single page load just to show company names.
        """
        cache_key = f"identity:{symbol}"
        cached = self.cache.get(cache_key)
        if cached and time.time() - cached[1] < 3600:
            return cached[0]
        identity: Dict = {}
        fh = await self._fetch_fh_company_info(symbol)
        if fh:
            identity = _map_av_fh_company_info_to_yf_schema(fh)
        if identity:
            self.cache[cache_key] = (identity, time.time())
        return identity

    async def get_indices(self, symbols: List[str]) -> List[Dict]:
        """Get market indices data.

        FIXED: this used to fall through to yFinance via the SAME shared
        circuit breaker used for stock quotes/historical/company info.
        Finnhub's free tier doesn't recognize these index symbols
        (^GSPC, ^VIX, BTC-USD, etc.) at all, so every single index was
        hitting yFinance every cycle — tripping the shared breaker before
        any real stock lookup even happened, which then blocked yFinance
        for company fundamentals too (the one place we actually need it,
        since only yFinance's .info has P/E, P/B, ROE, etc. in full).
        Indices now go through their own ISOLATED rate limiter
        (yf_indices_rate_limiter) — they can still get real yFinance data
        when it's available, but their failures can never again block
        fundamentals from getting their own shot at yFinance.
        """
        results = []
        for symbol in symbols:
            try:
                # FIXED: Finnhub's free plan has none of these symbols
                # (^GSPC, GC=F, BTC-USD...): every 5-minute ticker refresh
                # spent 10 of the 60 calls/minute on guaranteed misses.
                is_index_like = symbol.startswith('^') or '=' in symbol or symbol.endswith('-USD')
                quote = None if is_index_like else await self._fetch_fh_quote(symbol)
                if quote:
                    result = {
                        "symbol": symbol,
                        "name": self._get_index_name(symbol),
                        "value": quote.get("price", 0),
                        "change": quote.get("change_percent", 0),
                        "source": "Finnhub"
                    }
                    self._last_good_indices[symbol] = result
                    results.append(result)
                    continue

                quote = await self._fetch_yf_index_quote(symbol)
                if quote:
                    result = {
                        "symbol": symbol,
                        "name": self._get_index_name(symbol),
                        "value": quote.get("price", 0),
                        "change": quote.get("change_percent", 0),
                        "source": "yFinance"
                    }
                    self._last_good_indices[symbol] = result
                    results.append(result)
                elif symbol in self._last_good_indices:
                    stale = dict(self._last_good_indices[symbol])
                    stale["is_stale"] = True
                    results.append(stale)
            except Exception as e:
                logger.warning(f"Failed to fetch index {symbol}: {e}")
                if symbol in self._last_good_indices:
                    stale = dict(self._last_good_indices[symbol])
                    stale["is_stale"] = True
                    results.append(stale)
        
        return results

    async def _fetch_yf_index_quote(self, symbol: str) -> Optional[Dict]:
        """yFinance quote fetch for indices only — uses its own isolated
        rate limiter/circuit breaker (yf_indices_rate_limiter), separate
        from the one stock quotes/historical/company-info depend on. See
        get_indices() docstring for why this separation matters."""
        if yf_indices_rate_limiter.is_blocked():
            return None
        try:
            await yf_indices_rate_limiter.acquire()
            loop = asyncio.get_event_loop()
            stock = await asyncio.wait_for(loop.run_in_executor(None, yf.Ticker, symbol), timeout=8)
            info = await asyncio.wait_for(loop.run_in_executor(None, lambda: stock.info or {}), timeout=8)
            self.yf_calls += 1
            price = info.get('regularMarketPrice') or info.get('currentPrice')
            if price:
                self.yf_success += 1
                yf_indices_rate_limiter.record_success()
                prev_close = info.get('regularMarketPreviousClose') or info.get('previousClose') or price
                change_pct = ((price - prev_close) / prev_close * 100) if prev_close else 0
                return {"price": float(price), "change_percent": round(change_pct, 2)}
            yf_indices_rate_limiter.record_failure()
            return None
        except Exception as e:
            yf_indices_rate_limiter.record_failure()
            logger.warning(f"yFinance index quote error for {symbol}: {type(e).__name__}: {e}")
            return None
    
    def _get_index_name(self, symbol: str) -> str:
        names = {
            '^GSPC': 'S&P 500',
            '^IXIC': 'NASDAQ',
            '^DJI': 'DOW JONES',
            '^RUT': 'RUSSELL 2000',
            '^VIX': 'VIX',
            '^NSEI': 'NIFTY 50',
            '^BSESN': 'SENSEX',
            'BTC-USD': 'Bitcoin',
            'GC=F': 'Gold',
            'CL=F': 'Crude Oil'
        }
        return names.get(symbol, symbol)
    
    def get_stats(self) -> Dict:
        """Get engine statistics"""
        now = time.time()
        return {
            "finnhub": {
                "enabled": self.fh_enabled,
                "calls": self.fh_calls,
                "success": self.fh_success,
                "rate_limit": len([t for t in self.fh_calls_minute if now - t < 60])
            },
            "alpha_vantage": {
                "enabled": self.av_enabled,
                "calls": self.av_calls,
                "success": self.av_success,
                "rate_limit": len([t for t in self.av_calls_minute if now - t < 60])
            },
            "yfinance": {
                "enabled": True,
                "calls": self.yf_calls,
                "success": self.yf_success
            },
            "nse_direct": {
                "enabled": True,
                "calls": self.nse_provider.calls,
                "success": self.nse_provider.success
            },
            "cache_size": len(self.cache)
        }


# ============= RATE LIMITER =============
class YFinanceRateLimiter:
    def __init__(self, max_calls_per_minute=25):
        self.calls = []
        self.max_calls = max_calls_per_minute
        self.lock = asyncio.Lock()
        # Circuit breaker: when Yahoo is actively rate-limiting/blocking us
        # (common on cloud hosts like Render), repeatedly retrying every
        # ~60s per symbol just wastes calls and floods the logs without
        # ever succeeding. After enough consecutive failures, stop calling
        # yfinance entirely for a cooldown window.
        self.consecutive_failures = 0
        self.failure_threshold = 5
        self.cooldown_seconds = 300  # 5 minutes
        self.blocked_until = 0

    def is_blocked(self) -> bool:
        return time.time() < self.blocked_until

    def record_success(self):
        self.consecutive_failures = 0
        self.blocked_until = 0

    def record_failure(self):
        self.consecutive_failures += 1
        if self.consecutive_failures >= self.failure_threshold:
            self.blocked_until = time.time() + self.cooldown_seconds
            logger.warning(
                f"yFinance circuit breaker OPEN after {self.consecutive_failures} "
                f"consecutive failures — skipping yFinance calls for {self.cooldown_seconds}s"
            )

    async def acquire(self):
        async with self.lock:
            now = time.time()
            self.calls = [t for t in self.calls if now - t < 60]
            if len(self.calls) >= self.max_calls:
                wait_time = 60 - (now - self.calls[0]) + 0.5
                if wait_time > 0:
                    await asyncio.sleep(wait_time)
            self.calls.append(time.time())

# Initialize Hybrid Engine
hybrid_engine = HybridDataEngine()

# ============= WEBSOCKET MANAGER =============
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self.subscriptions: Dict[str, List[WebSocket]] = {}

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        for symbol in list(self.subscriptions.keys()):
            self.unsubscribe(websocket, symbol)

    def unsubscribe(self, websocket: WebSocket, symbol: str):
        subscribers = self.subscriptions.get(symbol)
        if not subscribers:
            return
        if websocket in subscribers:
            subscribers.remove(websocket)
        if not subscribers:
            # No one is watching this symbol anymore — stop polling it.
            self.subscriptions.pop(symbol, None)

    async def subscribe(self, websocket: WebSocket, symbol: str):
        if symbol not in self.subscriptions:
            self.subscriptions[symbol] = []
        if websocket not in self.subscriptions[symbol]:
            self.subscriptions[symbol].append(websocket)

    async def broadcast_to_symbol(self, symbol: str, message: dict):
        if symbol in self.subscriptions:
            dead = []
            for connection in list(self.subscriptions.get(symbol, [])):
                try:
                    await connection.send_json(message)
                except Exception:
                    dead.append(connection)
            for d in dead:
                self.disconnect(d)

    async def broadcast_all(self, message: dict):
        dead = []
        for connection in list(self.active_connections):
            try:
                await connection.send_json(message)
            except Exception:
                dead.append(connection)
        for d in dead:
            self.disconnect(d)

manager = ConnectionManager()

# ============= CONFIGURATION =============
class Config:
    API_TITLE = "StockVision Pro API"
    API_VERSION = "2.3.0"
    CACHE_TTL = int(os.getenv("CACHE_TTL", 300))
    MAX_CACHE_SIZE = 1000
    MAX_COMPARISON_STOCKS = int(os.getenv("MAX_COMPARISON_STOCKS", 5))
    MIN_COMPARISON_STOCKS = int(os.getenv("MIN_COMPARISON_STOCKS", 2))
    ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "*").split(",")

config = Config()

# One year of daily bars: enough for SMA-200, a meaningful annualized
# volatility, and a real 52-week high/low fallback.
ANALYSIS_HISTORY_PERIOD = "1y"

# ============= LRU CACHE =============
class LRUCache:
    def __init__(self, max_size=1000, ttl=300):
        self.cache = OrderedDict()
        self.timestamps = {}
        self.max_size = max_size
        self.ttl = ttl
        self.hits = 0
        self.misses = 0

    def get(self, key):
        if key not in self.cache:
            self.misses += 1
            return None
        if time.time() - self.timestamps[key] > self.ttl:
            self.delete(key)
            self.misses += 1
            return None
        self.cache.move_to_end(key)
        self.hits += 1
        return self.cache[key]

    def set(self, key, value):
        if key in self.cache:
            self.cache.move_to_end(key)
        self.cache[key] = value
        self.timestamps[key] = time.time()
        if len(self.cache) > self.max_size:
            oldest_key = next(iter(self.cache))
            self.delete(oldest_key)

    def delete(self, key):
        if key in self.cache:
            del self.cache[key]
            del self.timestamps[key]

    def delete_pattern(self, pattern: str):
        keys_to_delete = [k for k in self.cache.keys() if pattern in k]
        for key in keys_to_delete:
            self.delete(key)

    def clear(self):
        self.cache.clear()
        self.timestamps.clear()

    def stats(self):
        total = self.hits + self.misses
        hit_rate = (self.hits / total * 100) if total > 0 else 0
        return {
            "size": len(self.cache),
            "hits": self.hits,
            "misses": self.misses,
            "hit_rate": f"{hit_rate:.2f}%",
            "max_size": self.max_size
        }

stock_cache = LRUCache(max_size=config.MAX_CACHE_SIZE, ttl=config.CACHE_TTL)
chart_cache = LRUCache(max_size=config.MAX_CACHE_SIZE, ttl=config.CACHE_TTL)
# Long-lived cache of the last successfully fetched REAL data per symbol
# (6 hour TTL). Checked before ever falling back to the hardcoded demo
# dataset, so a transient yfinance/Finnhub/AlphaVantage hiccup shows a
# slightly stale REAL price instead of swapping to a fake one — this is
# what was causing prices to visibly "jump" between the real quote and
# the hardcoded fallback number.
last_good_stock_cache = LRUCache(max_size=config.MAX_CACHE_SIZE, ttl=21600)
last_good_chart_cache = LRUCache(max_size=config.MAX_CACHE_SIZE, ttl=21600)
yf_rate_limiter = YFinanceRateLimiter(max_calls_per_minute=25)
# Isolated from yf_rate_limiter on purpose — see get_indices() docstring.
# Indices fail against yFinance far more often than real stock lookups
# (Finnhub's free tier doesn't cover index symbols at all), and letting
# that trip the SAME breaker used for company fundamentals was starving
# fundamentals of yFinance access before they ever got a chance to use it.
yf_indices_rate_limiter = YFinanceRateLimiter(max_calls_per_minute=15)

request_counts = defaultdict(list)

# ============= FASTAPI APP =============
app = FastAPI(
    title=config.API_TITLE,
    version=config.API_VERSION,
    description="AI-powered stock analysis with Optimized Hybrid Engine",
    docs_url="/api/docs",
    redoc_url="/api/redoc"
)

# FIXED: ALLOWED_ORIGINS was read from the environment into config but
# never used — CORS was hardcoded to "*". It's honored now (default is
# still "*"). Credentials are only allowed with an explicit origin list,
# since the browser spec forbids credentials with a wildcard origin and the
# frontend never sends cookies anyway.
_allowed_origins = [o.strip() for o in config.ALLOWED_ORIGINS if o.strip()] or ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials="*" not in _allowed_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_client_ip(request: Optional[Request]) -> str:
    """Real client IP, even behind Render/Railway/Vercel's proxy.

    FIXED: request.client.host on a hosted platform is the platform's own
    load balancer, not the visitor. The per-IP limiter below therefore put
    EVERY visitor in one shared 60-requests/minute bucket — a single page
    load fires ~5 requests and the ticker polls every minute, so a handful
    of simultaneous users started getting 429s. The AI per-user limiter had
    the same problem (10 AI calls/minute shared by everyone). The first
    X-Forwarded-For hop is the original client.
    """
    if request is None:
        return "anonymous"
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()
    return request.client.host if request.client else "unknown"


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    client_ip = get_client_ip(request)
    now = time.time()
    request_counts[client_ip] = [t for t in request_counts[client_ip] if now - t < 60]
    # Drop idle IPs so the dict doesn't grow forever.
    if len(request_counts) > 5000:
        for ip in [ip for ip, ts in request_counts.items() if not ts]:
            del request_counts[ip]
    if len(request_counts[client_ip]) >= 60:
        return JSONResponse(
            status_code=429,
            content={"error": "Rate limit exceeded. Please try again in a minute."}
        )
    request_counts[client_ip].append(now)
    response = await call_next(request)
    response.headers["X-RateLimit-Limit"] = "60"
    response.headers["X-RateLimit-Remaining"] = str(60 - len(request_counts[client_ip]))
    return response

# ============= MODELS =============
# FIXED: the old pattern ^[A-Z0-9]{1,10}(\.[A-Z]{2,3})?$ rejected real
# tickers: hyphenated ones (BRK-B, BAJAJ-AUTO.NS) and ampersands (M&M.NS).
SYMBOL_PATTERN = re.compile(r'^[A-Z0-9&\-]{1,15}(\.[A-Z]{1,3})?$')


class StockRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=20)

    @validator('symbol')
    def validate_symbol(cls, v):
        v = v.upper().strip()
        if not v:
            raise ValueError('Symbol cannot be empty')
        if not SYMBOL_PATTERN.match(v):
            raise ValueError('Invalid symbol format')
        return v

class CompareRequest(BaseModel):
    symbols: List[str] = Field(..., min_items=2, max_items=5)

    @validator('symbols')
    def validate_symbols(cls, v):
        if len(v) < config.MIN_COMPARISON_STOCKS:
            raise ValueError(f'At least {config.MIN_COMPARISON_STOCKS} symbols required')
        if len(v) > config.MAX_COMPARISON_STOCKS:
            raise ValueError(f'Maximum {config.MAX_COMPARISON_STOCKS} symbols allowed')
        cleaned = []
        for symbol in v:
            symbol = symbol.upper().strip()
            if not SYMBOL_PATTERN.match(symbol):
                raise ValueError(f'Invalid symbol: {symbol}')
            cleaned.append(symbol)
        if len(cleaned) != len(set(cleaned)):
            raise ValueError('Duplicate symbols detected')
        return cleaned

# ============= WEBSOCKET =============
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """Live price subscriptions.

    FIXED:
    - Symbols are normalized (upper-case, stripped) and validated. A
      lower-case or junk symbol used to create its own subscription key,
      which price_updater then polled through the data providers every 5s
      forever.
    - Empty subscription lists are removed on unsubscribe, so
      price_updater stops fetching symbols nobody is watching anymore
      (they used to stay in the dict and be polled forever).
    - Any error other than a clean WebSocketDisconnect (e.g. the client
      vanishing mid-send) left the dead socket registered in
      active_connections and subscriptions. Cleanup now always runs.
    """
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            try:
                message = json.loads(data)
                if not isinstance(message, dict):
                    raise ValueError("message must be an object")
                message_type = message.get('type')
                raw_symbol = message.get('symbol')
                symbol = str(raw_symbol).upper().strip() if raw_symbol else ""
                if message_type == 'subscribe':
                    if symbol and SYMBOL_PATTERN.match(symbol):
                        await manager.subscribe(websocket, symbol)
                        await websocket.send_json({
                            "type": "subscribed",
                            "symbol": symbol,
                            "status": "success"
                        })
                        # A second viewer of an already-tracked symbol would
                        # otherwise wait until the price next moves before
                        # seeing anything — send the latest known quote now.
                        cached_quote = hybrid_engine.cache.get(f"quote:{symbol}")
                        if cached_quote and cached_quote[0].get('price'):
                            q = cached_quote[0]
                            await websocket.send_json({
                                "type": "price_update",
                                "symbol": symbol,
                                "price": round(q['price'], 2),
                                "change": round(q.get('change_percent', 0) or 0, 2),
                                "timestamp": datetime.now().isoformat(),
                                "source": q.get('source', 'unknown')
                            })
                    else:
                        await websocket.send_json({"type": "error", "message": "Invalid symbol"})
                elif message_type == 'unsubscribe':
                    manager.unsubscribe(websocket, symbol)
                elif message_type == 'ping':
                    await websocket.send_json({"type": "pong"})
            except (json.JSONDecodeError, ValueError):
                await websocket.send_json({"type": "error", "message": "Invalid JSON"})
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.debug(f"WebSocket closed with error: {type(e).__name__}: {e}")
    finally:
        manager.disconnect(websocket)

# ============= BACKGROUND TASKS =============
async def _fetch_indices_internal() -> list:
    """Internal function to fetch market indices using hybrid engine"""
    indices_config = [
        '^GSPC', '^IXIC', '^DJI', '^RUT', '^VIX',
        '^NSEI', '^BSESN', 'BTC-USD', 'GC=F', 'CL=F'
    ]
    return await hybrid_engine.get_indices(indices_config)

async def market_updater():
    """Periodically refresh market indices and push to WebSocket subscribers.

    FIXED: this was refetching all 10 index symbols via yFinance every 60
    seconds — 600 calls/hour just for the ticker tape, which was the
    single biggest driver of Yahoo's rate limiting on Render's shared IP
    (the circuit breaker was tripping within 1 second of every restart,
    before any real user request even happened). Indices don't need
    per-minute freshness for this app; 5 minutes is a much safer rate
    while still feeling "live" to users.
    """
    while True:
        try:
            stock_cache.delete_pattern("market:indices")
            indices = await _fetch_indices_internal()
            if indices:
                stock_cache.set("market:indices", {"indices": indices, "_timestamp": time.time()})
                await manager.broadcast_all({
                    "type": "market_update",
                    "data": indices,
                    "timestamp": datetime.now().isoformat()
                })
                logger.info(f"Market indices updated via WebSocket ({len(indices)} indices)")
        except Exception as e:
            logger.error(f"Error in market updater: {e}")
        await asyncio.sleep(300)

async def price_updater():
    """Push real-time price updates using hybrid engine"""
    last_prices: Dict[str, float] = {}
    consecutive_failures: Dict[str, int] = defaultdict(int)
    backoff_times: Dict[str, float] = defaultdict(float)

    while True:
        try:
            symbols = list(manager.subscriptions.keys())
            if symbols:
                batch_size = 10
                for i in range(0, len(symbols), batch_size):
                    batch = symbols[i:i + batch_size]
                    for symbol in batch:
                        if backoff_times[symbol] > time.time():
                            continue
                        try:
                            # Use hybrid engine for quote (fast)
                            quote = await hybrid_engine.get_quote(symbol)
                            
                            if quote and quote.get('price'):
                                current_price = quote['price']
                                change = quote.get('change_percent', 0)

                                # FIXED: the old condition was
                                # `abs(price - last) > 0.05 or abs(change) > 0.5`
                                # with last defaulting to the current price.
                                # On a calm day (|change| < 0.5%) the first
                                # tick was never sent, so subscribers never got
                                # a live price at all; on a volatile day the
                                # SAME cached price was re-broadcast every 5s
                                # because the daily % alone kept the condition
                                # true. Now: send the first tick, then only
                                # when the price actually moves.
                                last_price = last_prices.get(symbol)
                                if last_price is None or abs(current_price - last_price) >= 0.01:
                                    await manager.broadcast_to_symbol(symbol, {
                                        "type": "price_update",
                                        "symbol": symbol,
                                        "price": round(current_price, 2),
                                        "change": round(change, 2),
                                        "timestamp": datetime.now().isoformat(),
                                        "source": quote.get('source', 'unknown')
                                    })
                                    last_prices[symbol] = current_price
                                consecutive_failures[symbol] = 0
                                backoff_times[symbol] = 0.0
                            else:
                                consecutive_failures[symbol] += 1
                                if consecutive_failures[symbol] >= 3:
                                    backoff_times[symbol] = time.time() + 60
                        except Exception as e:
                            logger.debug(f"Price update error for {symbol}: {e}")
                            consecutive_failures[symbol] += 1
                    await asyncio.sleep(0.5)  # Faster updates
            update_interval = 5  # Faster updates
            await asyncio.sleep(update_interval)
        except Exception as e:
            logger.error(f"Error in price updater: {e}")
            await asyncio.sleep(5)

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(market_updater())
    asyncio.create_task(price_updater())
    logger.info("Background tasks started with Optimized Hybrid Engine")

# ============= HELPER FUNCTIONS =============
def safe_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default

def safe_get(dictionary: Optional[Dict], key: str, default: Any = None) -> Any:
    return dictionary.get(key, default) if dictionary else default

def invalidate_symbol_cache(symbol: str):
    stock_cache.delete_pattern(symbol)
    chart_cache.delete_pattern(symbol)

def get_fallback_stock_data(symbol: str) -> Dict:
    """Fallback data when all APIs fail"""
    fallback_prices = {
        "AAPL":  {"price": 175.50, "change": 0.5,  "company": "Apple Inc.",          "pe": 28.5, "market_cap": 2750000000000},
        "MSFT":  {"price": 420.75, "change": 0.3,  "company": "Microsoft Corp",       "pe": 35.2, "market_cap": 3120000000000},
        "GOOGL": {"price": 140.25, "change": 0.2,  "company": "Alphabet Inc",         "pe": 25.8, "market_cap": 1850000000000},
        "AMZN":  {"price": 178.50, "change": 0.4,  "company": "Amazon.com Inc",       "pe": 42.1, "market_cap": 1850000000000},
        "TSLA":  {"price": 240.50, "change": -0.3, "company": "Tesla Inc",            "pe": 45.3, "market_cap":  765000000000},
        "NVDA":  {"price": 850.00, "change": 1.2,  "company": "NVIDIA Corp",          "pe": 65.5, "market_cap": 2120000000000},
        "META":  {"price": 485.00, "change": 0.8,  "company": "Meta Platforms Inc",   "pe": 28.9, "market_cap": 1230000000000},
    }
    default = {"price": 100.00, "change": 0.0, "company": f"{symbol} Corp.", "pe": 20.0, "market_cap": 100000000000}
    data = fallback_prices.get(symbol, default)
    return {
        "symbol": symbol,
        "company_name": data["company"],
        "current_price": data["price"],
        "change_percent": data["change"],
        "previous_close": round(data["price"] * (1 - data["change"] / 100), 2),
        "change": round(data["price"] * data["change"] / 100, 2),
        "day_high": round(data["price"] * 1.02, 2),
        "day_low": round(data["price"] * 0.98, 2),
        "volume": 10_000_000,
        "pe_ratio": data["pe"],
        "pb_ratio": 4.5,
        "dividend_yield": 0.5,
        "market_cap": data["market_cap"],
        "eps": round(data["price"] / data["pe"], 2) if data["pe"] else 5.0,
        "roe": 25.0,
        "roa": 12.0,
        "current_ratio": 1.5,
        "debt_to_equity": 0.8,
        "volatility": 0.35,
        "fifty_two_week_high": round(data["price"] * 1.15, 2),
        "fifty_two_week_low":  round(data["price"] * 0.85, 2),
        "average_volume": 15_000_000,
        "sector": "Technology",
        "industry": "Software",
        "exchange": "NASDAQ",
        "ai_score": 70,
        "recommendation": "Hold",
        "confidence": "Moderate",
        "risk_level": "Moderate Risk",
        "growth_potential": "Moderate Growth",
        "valuation": "Fairly Valued",
        "technical_indicators": {
            "rsi": 55, "trend": "Neutral",
            "sma_20": round(data["price"] * 0.98, 2),
            "sma_50": round(data["price"] * 0.95, 2),
            "sma_200": round(data["price"] * 0.90, 2),
            "macd": 0.5, "signal": 0.3, "histogram": 0.2
        },
        "news": [{"title": f"{data['company']} latest news", "publisher": "Reuters", "published": datetime.now().isoformat()}],
        "ownership": {"institutional_holders": 65.0, "insider_holders": 5.0},
        "growth_metrics": {"revenue_growth": 12.5, "earnings_growth": 15.0},
        "is_fallback_data": True,
        "message": "Using estimated data — live data temporarily unavailable",
        "last_updated": datetime.now().isoformat()
    }

def _map_av_fh_company_info_to_yf_schema(company_info: Dict) -> Dict:
    """
    Translate Alpha Vantage / Finnhub's company_info output (snake_case:
    pe_ratio, market_cap, roe, debt_to_equity...) into yfinance's native
    camelCase schema (trailingPE, marketCap, returnOnEquity,
    debtToEquity...), which is what financials.py's calculate_pe_ratio /
    calculate_pb_ratio / calculate_roe / etc. and build_stock_response
    actually read.

    BUG THIS FIXES: company_info used to be merged directly, so a
    successful Alpha Vantage or Finnhub fetch silently produced
    Market Cap / P/E / P/B / EPS / ROE / D-E = N/A across the board (key
    names never matched what the calculators looked for), even though
    the real data had arrived. yFinance's own company info is already in
    this schema and must NOT be passed through this mapper (it uses
    different, snake_case-free key names already) — see get_company_info().
    """
    if not company_info:
        return {}

    mapped = {}
    for key in ("sector", "industry", "exchange", "country"):
        if company_info.get(key) is not None:
            mapped[key] = company_info[key]

    if company_info.get("company_name") is not None:
        mapped["longName"] = company_info["company_name"]
        mapped["shortName"] = company_info["company_name"]
    if company_info.get("market_cap") is not None:
        mapped["marketCap"] = company_info["market_cap"]
    if company_info.get("pe_ratio") is not None:
        mapped["trailingPE"] = company_info["pe_ratio"]
    if company_info.get("pb_ratio") is not None:
        mapped["priceToBook"] = company_info["pb_ratio"]
    if company_info.get("roe") is not None:
        mapped["returnOnEquity"] = company_info["roe"]
    if company_info.get("roa") is not None:
        mapped["returnOnAssets"] = company_info["roa"]
    if company_info.get("dividend_yield") is not None:
        mapped["dividendYield"] = company_info["dividend_yield"]
    if company_info.get("eps") is not None:
        mapped["trailingEps"] = company_info["eps"]
    if company_info.get("debt_to_equity") is not None:
        mapped["debtToEquity"] = company_info["debt_to_equity"]
    if company_info.get("revenue_growth") is not None:
        mapped["revenueGrowth"] = company_info["revenue_growth"]

    return mapped

async def fetch_stock_data(symbol: str, use_cache: bool = True):
    """Fetch stock data using hybrid engine with fallback"""
    cache_key = f"stock_data:{symbol}"
    if use_cache:
        cached = stock_cache.get(cache_key)
        if cached:
            return cached

    try:
        symbol = symbol.upper().strip()
        symbol_map = {"NVD": "NVDA", "BRK.B": "BRK-B", "BF.B": "BF-B"}
        symbol = symbol_map.get(symbol, symbol)

        # Use hybrid engine for quote (fastest available)
        quote = await hybrid_engine.get_quote(symbol)

        # FIXED: analysis used to pull only "1mo" of history (~21 trading
        # days). That made SMA-50 and SMA-200 permanently impossible (the
        # UI never showed them, despite the README advertising them), left
        # volatility computed from barely 20 returns, and the "52W
        # High/Low" fallback was really a 1-month high/low. One year of
        # daily bars costs the same single yFinance/NSE request, and it
        # shares its cache with the 1Y chart.
        hist_data = await hybrid_engine.get_historical(symbol, ANALYSIS_HISTORY_PERIOD, "1d")

        # Get company info (priority: Alpha Vantage → Finnhub → yFinance)
        company_info = await hybrid_engine.get_company_info(symbol)

        # If we have quote data, convert to yFinance-like format
        if quote:
            class MockStock:
                def __init__(self, info_dict):
                    self.info = info_dict

            quote_fields = {
                "symbol": symbol,
                "currentPrice": quote.get("price", 0),
                "regularMarketPrice": quote.get("price", 0),
                "previousClose": quote.get("previous_close", 0),
                "regularMarketChange": quote.get("change", 0),
                "regularMarketChangePercent": quote.get("change_percent", 0),
                "volume": quote.get("volume", 0),
                "dayHigh": quote.get("high", 0),
                "dayLow": quote.get("low", 0),
                "open": quote.get("open", 0),
            }

            # FIXED: this used to be info = quote_fields; info.update(company_info).
            # When the company info came from yFinance (the usual case for
            # the ratio fields), its .info dict ALSO contains currentPrice,
            # previousClose, volume, dayHigh, dayLow... — so update()
            # silently overwrote the real-time Finnhub/NSE quote with
            # yFinance's delayed snapshot. The header price and change %
            # then disagreed with the live WebSocket ticks. Company info is
            # now the base layer and the live quote is applied on top.
            info = {**(company_info or {}), **quote_fields}

            # FIXED: Finnhub's /quote response has no volume field at all,
            # so every US stock quoted through Finnhub showed volume 0 ("Vol:
            # N/A" in the header). Fall back to the company-info volume
            # when the quote didn't carry one.
            if not quote_fields["volume"] and company_info:
                fallback_volume = company_info.get("volume") or company_info.get("regularMarketVolume")
                if fallback_volume:
                    info["volume"] = fallback_volume

            stock = MockStock(info)
            
            # Convert historical data to DataFrame
            # FIXED: pandas was only imported inside the `if hist_data:`
            # branch — when hist_data was falsy (increasingly common now
            # that Finnhub/AV fail more often), the `else` branch tried to
            # use `pd` on a code path where it had never been bound,
            # raising "cannot access local variable 'pd'" and crashing
            # the entire request instead of gracefully falling through to
            # cached/fallback data as intended.
            import pandas as pd
            if hist_data:
                df_data = []
                for item in hist_data:
                    df_data.append({
                        "Date": pd.to_datetime(item["date"]),
                        "Close": item["price"],
                        "Open": item["open"],
                        "High": item["high"],
                        "Low": item["low"],
                        "Volume": item["volume"]
                    })
                hist = pd.DataFrame(df_data).set_index("Date")
            else:
                hist = pd.DataFrame()
            
            result = (stock, info, hist)
            if use_cache:
                stock_cache.set(cache_key, result)
            return result

        # Ultimate fallback to yFinance (timeout-bounded — see hybrid
        # engine's _fetch_yf_* methods for why this matters: an unbounded
        # yfinance call here could hang the whole /api/stock/{symbol}
        # request well past the frontend's 30s timeout)
        # FIXED: this path used to call yf_rate_limiter.acquire() without
        # ever checking is_blocked() first, so while the circuit breaker
        # was open (Yahoo actively blocking us) it still fired a doomed
        # request on every single lookup instead of failing fast.
        if yf_rate_limiter.is_blocked():
            logger.warning(f"yFinance ultimate fallback skipped for {symbol} — circuit breaker open")
            return None, {}, None
        await yf_rate_limiter.acquire()
        loop = asyncio.get_event_loop()
        try:
            stock = await asyncio.wait_for(loop.run_in_executor(None, yf.Ticker, symbol), timeout=8)
            info = await asyncio.wait_for(loop.run_in_executor(None, lambda: stock.info or {}), timeout=8)
            hist = await asyncio.wait_for(
                loop.run_in_executor(None, lambda: stock.history(period=ANALYSIS_HISTORY_PERIOD)),
                timeout=10
            )
        except asyncio.TimeoutError:
            yf_rate_limiter.record_failure()
            logger.warning(f"yFinance ultimate fallback timed out for {symbol}")
            return None, {}, None

        if hist is not None and not hist.empty:
            yf_rate_limiter.record_success()
            result = (stock, info, hist)
            if use_cache:
                stock_cache.set(cache_key, result)
            return result

        yf_rate_limiter.record_failure()
        return None, {}, None

    except Exception as e:
        logger.error(f"Error fetching {symbol}: {e}")
        return None, {}, None

def calculate_price_metrics(info: Dict, hist) -> Dict:
    try:
        current_price = (
            info.get('currentPrice') or
            info.get('regularMarketPrice') or
            info.get('previousClose') or
            (float(hist['Close'].iloc[-1]) if len(hist) > 0 else 0.0)
        )
        previous_close = (
            info.get('previousClose') or
            (float(hist['Close'].iloc[-2]) if len(hist) > 1 else current_price)
        )
        current_price = safe_float(current_price)
        previous_close = safe_float(previous_close)
        change = current_price - previous_close
        change_percent = ((change / previous_close) * 100) if previous_close else 0.0
        day_high = info.get('dayHigh') or (float(hist['High'].iloc[-1]) if len(hist) > 0 else current_price)
        day_low  = info.get('dayLow')  or (float(hist['Low'].iloc[-1])  if len(hist) > 0 else current_price)
        return {
            "current_price": round(current_price, 2),
            "previous_close": round(previous_close, 2),
            "change": round(change, 2),
            "change_percent": round(change_percent, 2),
            "day_high": round(safe_float(day_high), 2),
            "day_low":  round(safe_float(day_low),  2),
            "volume": safe_float(info.get('volume', 0))
        }
    except Exception as e:
        logger.error(f"Error calculating price metrics: {e}")
        return {"current_price": 0.0, "previous_close": 0.0, "change": 0.0, "change_percent": 0.0, "day_high": 0.0, "day_low": 0.0, "volume": 0}

news_cache = LRUCache(max_size=500, ttl=900)


async def fetch_news_async(symbol: str, max_news: int = 5) -> List[Dict]:
    """Non-blocking, timeout-bounded, cached news fetch.

    FIXED: build_stock_response() used to call get_latest_news() directly.
    That is a synchronous yFinance HTTP request, and build_stock_response
    runs inside async endpoints — so every analysis BLOCKED THE WHOLE EVENT
    LOOP for the duration of a Yahoo round-trip (no timeout, no circuit
    breaker). While it hung, every other user's request, the WebSocket
    price pushes and the background updaters all froze with it. /api/compare
    did this once per stock, serially, and /api/ai/thesis fetched the same
    news twice. News now runs in a worker thread with a timeout, respects
    the yFinance circuit breaker, and is cached for 15 minutes.
    """
    cache_key = f"news:{symbol}:{max_news}"
    cached = news_cache.get(cache_key)
    if cached is not None:
        return cached

    news: List[Dict] = []
    if not yf_rate_limiter.is_blocked():
        try:
            loop = asyncio.get_event_loop()
            news = await asyncio.wait_for(
                loop.run_in_executor(None, get_latest_news, symbol, max_news),
                timeout=8
            )
        except asyncio.TimeoutError:
            logger.warning(f"News fetch timed out for {symbol}")
        except Exception as e:
            logger.warning(f"News fetch failed for {symbol}: {e}")

    # FIXED: in production yFinance news came back empty for every symbol
    # (through the proxy) without raising, so news was always []. US
    # symbols now fall back to Finnhub's company-news endpoint, which is
    # on the free plan. Finnhub has no NSE/BSE coverage, so Indian symbols
    # only get yFinance news.
    if not news and not is_indian_stock(symbol):
        news = await _fetch_finnhub_news(symbol, max_news)

    # FIXED: an empty result used to be cached for the full 15 minutes, so
    # one failed fetch hid news for that symbol for a quarter of an hour.
    # Only real results are cached now.
    if news:
        news_cache.set(cache_key, news)
    return news


async def _fetch_finnhub_news(symbol: str, max_news: int) -> List[Dict]:
    """Company news from Finnhub (free plan, US symbols), last 7 days,
    in the same {title, publisher, link, published} shape as yFinance."""
    if not hybrid_engine.fh_enabled or not hybrid_engine._can_call_fh():
        return []
    try:
        today = datetime.now().date()
        start = (today - timedelta(days=7)).isoformat()
        loop = asyncio.get_event_loop()
        raw = await asyncio.wait_for(
            loop.run_in_executor(
                None, lambda: hybrid_engine.fh_client.company_news(symbol, _from=start, to=today.isoformat())
            ),
            timeout=8
        )
        hybrid_engine._record_fh_call()
    except Exception as e:
        logger.warning(f"Finnhub news error for {symbol}: {type(e).__name__}: {e}")
        return []

    items: List[Dict] = []
    for item in raw or []:
        title = (item.get("headline") or "").strip()
        if not title:
            continue
        ts = item.get("datetime")
        published = (
            datetime.utcfromtimestamp(ts).isoformat()
            if isinstance(ts, (int, float)) and ts > 0 else None
        )
        items.append({
            "title": title,
            "publisher": item.get("source") or "Unknown",
            "link": item.get("url") or "",
            "published": published,
        })
        if len(items) >= max_news:
            break
    return items


def build_stock_response(symbol: str, stock, info: Dict, hist, news: Optional[List[Dict]] = None) -> Dict:
    try:
        price_metrics    = calculate_price_metrics(info, hist)
        pe_ratio         = calculate_pe_ratio(info)
        pb_ratio         = calculate_pb_ratio(info)
        debt_to_equity   = calculate_debt_to_equity(info)
        current_ratio    = calculate_current_ratio(info)
        roe              = calculate_roe(info)
        roa              = calculate_roa(info)
        dividend_yield   = get_dividend_yield(info)
        eps              = calculate_eps(info)
        volatility       = calculate_volatility(hist)
        technical_indicators = calculate_technical_indicators(hist)
        growth_metrics   = analyze_growth(stock)
        ownership        = get_ownership_pattern(stock)
        news             = news or []

        metrics = {
            'pe_ratio': pe_ratio, 'pb_ratio': pb_ratio,
            'dividend_yield': dividend_yield, 'debt_to_equity': debt_to_equity,
            'eps': eps, 'roe': roe, 'roa': roa, 'current_ratio': current_ratio,
            'volatility': volatility, 'growth_metrics': growth_metrics,
            'technical_indicators': technical_indicators, 'sector': info.get('sector')
        }

        ai_score = calculate_ai_score(metrics)
        recommendation_data = generate_recommendation(ai_score, metrics)

        is_indian = is_indian_stock(symbol)
        display_symbol = normalize_indian_symbol(symbol) if is_indian else symbol
        company_name = safe_get(info, 'longName', display_symbol) or safe_get(info, 'shortName', display_symbol)

        market_cap = safe_float(safe_get(info, 'marketCap', 0))
        if market_cap == 0 and info.get('sharesOutstanding'):
            market_cap = safe_float(info['sharesOutstanding']) * price_metrics.get('current_price', 0)

        fifty_two_week_high = safe_float(safe_get(info, 'fiftyTwoWeekHigh', 0))
        fifty_two_week_low  = safe_float(safe_get(info, 'fiftyTwoWeekLow',  0))
        if fifty_two_week_high == 0 and hist is not None and not hist.empty:
            fifty_two_week_high = float(hist['High'].max())
            fifty_two_week_low  = float(hist['Low'].min())

        return {
            "symbol": display_symbol,
            "original_symbol": symbol,
            "is_indian_stock": is_indian,
            "company_name": company_name,
            **price_metrics,
            "market_cap": market_cap,
            "pe_ratio":        round(pe_ratio,       2) if pe_ratio       is not None else None,
            "pb_ratio":        round(pb_ratio,       2) if pb_ratio       is not None else None,
            "dividend_yield":  round(dividend_yield, 2) if dividend_yield is not None else None,
            "debt_to_equity":  round(debt_to_equity, 2) if debt_to_equity is not None else None,
            "eps":             round(eps,            2) if eps            is not None else None,
            "roe":             round(roe,            2) if roe            is not None else None,
            "roa":             round(roa,            2) if roa            is not None else None,
            "current_ratio":   round(current_ratio,  2) if current_ratio  is not None else None,
            "volatility":      round(volatility, 4),
            "fifty_two_week_high": round(fifty_two_week_high, 2),
            "fifty_two_week_low":  round(fifty_two_week_low,  2),
            "average_volume": safe_float(safe_get(info, 'averageVolume', 0)),
            "sector":   safe_get(info, 'sector'),
            "industry": safe_get(info, 'industry'),
            "exchange": safe_get(info, 'exchange'),
            "ai_score": round(ai_score, 2),
            "recommendation":  recommendation_data.get('recommendation', 'Hold'),
            "confidence":      recommendation_data.get('confidence', 'Moderate'),
            "risk_level":      recommendation_data.get('risk_level', 'Moderate Risk'),
            "growth_potential":recommendation_data.get('growth_potential', 'Moderate Growth'),
            "valuation":       recommendation_data.get('valuation', 'Fairly Valued'),
            "technical_indicators": technical_indicators,
            "news": news[:5],
            "ownership": ownership,
            "growth_metrics": growth_metrics,
            "last_updated": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Error building response for {symbol}: {e}")
        raise

# ============= API ENDPOINTS =============
@app.get("/")
async def root():
    return {
        "service": config.API_TITLE,
        "version": config.API_VERSION,
        "status": "operational",
        "hybrid_engine": hybrid_engine.get_stats(),
        "timestamp": datetime.now().isoformat()
    }

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "version": config.API_VERSION,
        "cache_stats": stock_cache.stats(),
        "hybrid_engine": hybrid_engine.get_stats()
    }

@app.get("/api/stock/{symbol}")
async def get_stock_analysis(symbol: str, use_cache: bool = True):
    try:
        symbol = symbol.upper().strip()
        cache_key = f"stock:{symbol}"
        if use_cache:
            cached = stock_cache.get(cache_key)
            if cached:
                return cached

        result, news = await asyncio.gather(
            fetch_stock_data(symbol, use_cache=False),
            fetch_news_async(symbol),
        )
        if result and result[0] is not None and result[2] is not None:
            stock, info, hist = result
            response_data = build_stock_response(symbol, stock, info, hist, news)
            if use_cache:
                stock_cache.set(cache_key, response_data)
            # Remember this as the last known-good REAL data for this symbol
            last_good_stock_cache.set(symbol, response_data)
            return response_data

        # Live sources failed this round — prefer the last successfully
        # fetched REAL data (even if a bit stale) over the hardcoded demo
        # dataset, so the price doesn't visibly jump to a fake number.
        last_good = last_good_stock_cache.get(symbol)
        if last_good:
            logger.warning(f"Live fetch failed for {symbol} — serving last known-good real data")
            stale_response = {**last_good, "is_stale": True}
            if use_cache:
                stock_cache.set(cache_key, stale_response)
            return stale_response

        logger.warning(f"Using fallback for {symbol} — no live or cached real data available")
        fallback = get_fallback_stock_data(symbol)
        if use_cache:
            stock_cache.set(cache_key, fallback)
        return fallback

    except Exception as e:
        logger.error(f"Error in get_stock_analysis for {symbol}: {e}")
        last_good = last_good_stock_cache.get(symbol.upper().strip())
        if last_good:
            return {**last_good, "is_stale": True}
        return get_fallback_stock_data(symbol)

@app.get("/api/stock/{symbol}/chart")
async def get_stock_chart(symbol: str, period: str = "1mo", use_cache: bool = True):
    try:
        symbol = symbol.upper().strip()
        valid_periods = {"1d", "5d", "1mo", "3mo", "6mo", "1y"}
        if period not in valid_periods:
            period = "1mo"

        cache_key = f"chart:{symbol}:{period}"
        if use_cache:
            cached = chart_cache.get(cache_key)
            if cached:
                return cached

        # Use hybrid engine for historical data (fast)
        interval = "1d" if period in {"1mo", "3mo", "6mo", "1y"} else "1h"
        try:
            hist_data = await hybrid_engine.get_historical(symbol, period, interval)
        except Exception as e:
            logger.warning(f"Hybrid engine historical failed for {symbol}: {e}")
            hist_data = None

        if hist_data and len(hist_data) > 0:
            chart_cache.set(cache_key, hist_data)
            last_good_chart_cache.set(cache_key, hist_data)
            return hist_data

        # NOTE: previously there was a second, redundant yfinance fallback
        # attempt here — but hybrid_engine.get_historical() above already
        # tries Finnhub → Alpha Vantage → yFinance internally (each leg
        # now timeout-bounded). Calling yfinance a second time just added
        # a duplicate unbounded network round-trip on top of the three the
        # hybrid engine already made, which was the main reason chart
        # requests could exceed the frontend's 30s timeout. Removed.

        # Prefer the last successfully fetched REAL chart data (even if a
        # bit stale) over randomly generated synthetic data — otherwise a
        # transient failure makes the price history visibly jump between
        # real and fake data on refresh.
        last_good = last_good_chart_cache.get(cache_key)
        if last_good:
            logger.warning(f"Live chart fetch failed for {symbol} — serving last known-good real chart data")
            return last_good

        # Synthetic fallback data (only reached when we've never
        # successfully fetched real chart data for this symbol/period).
        # FIXED: this used to seed the random walk from
        # get_fallback_stock_data()'s hardcoded demo price (~$175 for
        # AAPL) unconditionally — even when a REAL current price was
        # already known from a successful quote elsewhere (e.g. the main
        # /api/stock/{symbol} response). That produced a chart showing a
        # completely different price level than the real quote on the
        # same page (e.g. chart around $175 while the header showed
        # $316).
        #
        # FIXED (round 2): checking last_good_stock_cache alone isn't
        # enough — the frontend fires the chart request and the main
        # stock-analysis request in PARALLEL (intentionally, for speed),
        # so on a cold cache the chart request frequently finishes first,
        # before /api/stock/{symbol} has had a chance to populate
        # last_good_stock_cache with the real price at all. That race
        # meant this "fix" often silently did nothing. Now, if the cache
        # is empty, we fetch a live quote directly as a last resort
        # before falling to the fully-synthetic demo price — quote calls
        # are cheap/fast (a single lightweight request, not historical),
        # so this rarely fails even when historical data is unavailable.
        logger.info(f"Using synthetic chart data for {symbol} ({period}) — live sources unavailable")
        base_price = None
        real_last_known = last_good_stock_cache.get(symbol)
        if real_last_known and real_last_known.get('current_price'):
            base_price = real_last_known['current_price']
        else:
            try:
                live_quote = await hybrid_engine.get_quote(symbol)
                if live_quote and live_quote.get('price'):
                    base_price = live_quote['price']
            except Exception as e:
                logger.warning(f"Live quote anchor fetch failed for {symbol}: {e}")

        if base_price is None:
            stock_data = get_fallback_stock_data(symbol)
            base_price = stock_data.get('current_price', 100)
        days_map = {"1d": 1, "5d": 5, "1mo": 30, "3mo": 90, "6mo": 180, "1y": 365}
        days = days_map.get(period, 30)
        chart_data = []
        for i in range(days, -1, -1):
            date = datetime.now() - timedelta(days=i)
            change = random.uniform(-0.025, 0.025)
            price = base_price * (1 + change * (i / max(days, 1)))
            chart_data.append({
                "date": date.isoformat(),
                "price": round(max(price, 0.01), 2),
                "open":  round(price * random.uniform(0.99, 1.01), 2),
                "high":  round(price * random.uniform(1.005, 1.02), 2),
                "low":   round(price * random.uniform(0.98, 0.995), 2),
                "volume": random.randint(5_000_000, 25_000_000)
            })
        if use_cache:
            chart_cache.set(cache_key, chart_data)
        return chart_data

    except Exception as e:
        logger.error(f"Error fetching chart for {symbol}: {e}")
        return []

async def _load_stocks_for_comparison(symbols: List[str]):
    """Fetch and build every stock in a comparison concurrently.

    Shared by /api/compare and /api/ai/compare (they used to duplicate this
    loop with slightly different failure handling). Uses the same
    last-known-good fallback as /api/stock/{symbol}, so a transient outage
    shows slightly stale REAL data instead of the hardcoded demo dataset.
    """
    results, news_lists = await asyncio.gather(
        asyncio.gather(*[fetch_stock_data(s) for s in symbols], return_exceptions=True),
        asyncio.gather(*[fetch_news_async(s) for s in symbols]),
    )
    stocks_data: List[Dict] = []
    failed: List[str] = []
    for symbol, result, news in zip(symbols, results, news_lists):
        built = None
        if not isinstance(result, Exception) and result and result[0] is not None and result[2] is not None:
            try:
                stock, info, hist = result
                built = build_stock_response(symbol, stock, info, hist, news)
                last_good_stock_cache.set(symbol, built)
            except Exception as e:
                logger.warning(f"Comparison build failed for {symbol}: {e}")
        if built is None:
            failed.append(symbol)
            last_good = last_good_stock_cache.get(symbol)
            built = {**last_good, "is_stale": True} if last_good else get_fallback_stock_data(symbol)
        stocks_data.append(built)
    return stocks_data, failed


def _build_comparison_summary(stocks_data: List[Dict], failed: List[str]) -> Dict:
    """Rule-based winners per category.

    FIXED: average_debt used to average `debt_to_equity or 0` over EVERY
    stock — a stock with unknown D/E counted as zero debt and dragged the
    average down. Unknown values are excluded now, like P/E and ROE.
    Stocks served from the hardcoded demo dataset are also excluded from
    the "winner" picks, so a fake number can't be crowned best value.
    """
    real = [s for s in stocks_data if not s.get('is_fallback_data')] or stocks_data

    def pick(candidates, key, best):
        values = [s for s in candidates if isinstance(s.get(key), (int, float))]
        if not values:
            return "N/A"
        return best(values, key=lambda s: s[key])['symbol']

    def average(key):
        values = [s[key] for s in real if isinstance(s.get(key), (int, float))]
        return round(float(np.mean(values)), 2) if values else None

    positive_pe = [s for s in real if isinstance(s.get('pe_ratio'), (int, float)) and s['pe_ratio'] > 0]
    return {
        "ai_top_pick":   pick(real, 'ai_score', max),
        "best_value":    pick(positive_pe, 'pe_ratio', min),
        "best_dividend": pick(real, 'dividend_yield', max),
        "lowest_risk":   pick(real, 'volatility', min),
        "average_pe":    average('pe_ratio'),
        "average_roe":   average('roe'),
        "average_debt":  average('debt_to_equity'),
        "failed_symbols": failed,
    }


@app.post("/api/compare")
async def compare_stocks(request: CompareRequest):
    try:
        stocks_data, failed = await _load_stocks_for_comparison(request.symbols)
        return {"stocks": stocks_data, "comparison": _build_comparison_summary(stocks_data, failed)}
    except Exception as e:
        logger.error(f"Error comparing stocks: {e}")
        raise HTTPException(status_code=500, detail="Error comparing stocks")

@app.post("/api/ai/compare")
async def ai_compare_stocks(request: CompareRequest, req: Request):
    """FIXED: this is the endpoint the frontend actually calls for every
    comparison, but it never returned the `comparison` summary block. The
    Compare page therefore always took its "AI" branch and the whole
    metrics table (price, P/E, ROE, D/E, market cap, averages) was dead
    code that could never render. Both are returned now and the page shows
    both."""
    try:
        user_id = get_client_ip(req)
        stocks_data, failed = await _load_stocks_for_comparison(request.symbols)
        ai_analysis = await ai_service.analyze_stock_comparison(stocks_data, user_id=user_id)
        return {
            "success": True,
            "stocks": stocks_data,
            "comparison": _build_comparison_summary(stocks_data, failed),
            "ai_analysis": ai_analysis,
            "failed_symbols": failed,
            "rate_limit": ai_service.get_rate_limit_stats(),
            "hybrid_stats": hybrid_engine.get_stats(),
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Error in AI comparison: {e}")
        return {"success": False, "error": str(e)}

@app.get("/api/ai/thesis/{symbol}")
async def get_ai_thesis(symbol: str, req: Request):
    try:
        symbol = symbol.upper().strip()
        user_id = get_client_ip(req)
        result, news = await asyncio.gather(fetch_stock_data(symbol), fetch_news_async(symbol))
        if result and result[0] is not None and result[2] is not None:
            stock, info, hist = result
            stock_data = build_stock_response(symbol, stock, info, hist, news)
        else:
            stock_data = get_fallback_stock_data(symbol)
        thesis = await ai_service.generate_investment_thesis(stock_data, news, user_id=user_id)
        return {"success": True, "symbol": symbol, "thesis": thesis, "timestamp": datetime.now().isoformat()}
    except Exception as e:
        logger.error(f"Error generating thesis: {e}")
        return {"success": False, "error": str(e)}

@app.post("/api/ai/question")
async def ask_ai_question(request: dict, req: Request):
    try:
        question = request.get("question")
        symbol   = request.get("symbol")
        user_id  = get_client_ip(req)
        if not question:
            return {"success": False, "error": "Question is required"}
        stock_data = None
        if symbol:
            symbol = str(symbol).upper().strip()
            try:
                result = await fetch_stock_data(symbol)
                if result and result[0] is not None and result[2] is not None:
                    stock, info, hist = result
                    stock_data = build_stock_response(symbol, stock, info, hist)
                else:
                    stock_data = get_fallback_stock_data(symbol)
            except Exception:
                stock_data = get_fallback_stock_data(symbol)
        answer = await ai_service.answer_question(question, stock_data, user_id=user_id)
        return {"success": True, "question": question, "answer": answer, "timestamp": datetime.now().isoformat()}
    except Exception as e:
        logger.error(f"Error answering question: {e}")
        return {"success": False, "error": str(e)}

@app.post("/api/ai/sentiment")
async def analyze_sentiment(request: dict, req: Request):
    try:
        symbols = [str(s).upper().strip() for s in (request.get("symbols") or [])][:config.MAX_COMPARISON_STOCKS]
        user_id = get_client_ip(req)
        if not symbols:
            return {"success": False, "error": "Symbols required"}
        news_lists = await asyncio.gather(*[fetch_news_async(s, max_news=3) for s in symbols])
        news_data = dict(zip(symbols, news_lists))
        sentiment = await ai_service.get_market_sentiment(symbols, news_data, user_id=user_id)
        return {"success": True, "sentiment": sentiment, "timestamp": datetime.now().isoformat()}
    except Exception as e:
        logger.error(f"Error analyzing sentiment: {e}")
        return {"success": False, "error": str(e)}

@app.get("/api/market-indices")
async def get_market_indices(use_cache: bool = True):
    """Get major market indices using hybrid engine"""
    cache_key = "market:indices"
    if use_cache:
        cached = stock_cache.get(cache_key)
        if cached:
            ts = cached.get("_timestamp", 0) if isinstance(cached, dict) else 0
            if time.time() - ts < 280:
                return cached.get("indices", cached) if isinstance(cached, dict) else cached

    valid_indices = await _fetch_indices_internal()

    if len(valid_indices) == 0:
        cached = stock_cache.get(cache_key)
        if cached:
            return cached.get("indices", cached) if isinstance(cached, dict) else cached
        return []

    if use_cache and valid_indices:
        stock_cache.set(cache_key, {"indices": valid_indices, "_timestamp": time.time()})

    return valid_indices

@app.get("/api/trending")
async def get_trending(use_cache: bool = True):
    cache_key = "trending:stocks"
    if use_cache:
        cached = stock_cache.get(cache_key)
        if cached:
            return cached

    symbols = ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'TSLA', 'NVDA', 'META']

    async def fetch_trending(symbol):
        # FIXED (2 bugs):
        # 1. get_company_info() returns yFinance's camelCase schema
        #    (longName, marketCap) since the schema-mapping fix, but this
        #    still read 'company_name' / 'market_cap' — so every trending
        #    stock showed its ticker as its name and a market cap of 0.
        # 2. get_company_info() also spent an Alpha Vantage call per symbol:
        #    7 of the 25 daily calls gone on every uncached page load, just
        #    for display names. get_company_identity() uses Finnhub only.
        try:
            quote, identity = await asyncio.gather(
                hybrid_engine.get_quote(symbol),
                hybrid_engine.get_company_identity(symbol),
            )

            if quote and quote.get('price'):
                return {
                    "symbol": symbol,
                    "name": identity.get('longName') or identity.get('shortName') or symbol,
                    "price": quote.get('price', 0),
                    "change": quote.get('change_percent', 0),
                    "volume": quote.get('volume', 0),
                    "market_cap": identity.get('marketCap', 0) or 0,
                    "source": quote.get('source', 'unknown')
                }
        except Exception as e:
            logger.error(f"Error fetching trending {symbol}: {e}")
        return None

    results = await asyncio.gather(*[fetch_trending(s) for s in symbols])
    trending_data = [r for r in results if r]
    response = {"trending": trending_data}
    if use_cache:
        stock_cache.set(cache_key, response)
    return response

@app.get("/api/search/{query}")
async def search_stocks(query: str):
    if len(query) < 2:
        return {"results": []}
    stock_db = {
        "AAPL": "Apple Inc.", "MSFT": "Microsoft Corporation", "GOOGL": "Alphabet Inc.",
        "AMZN": "Amazon.com Inc.", "TSLA": "Tesla Inc.", "NVDA": "NVIDIA Corporation",
        "META": "Meta Platforms Inc.", "JPM": "JPMorgan Chase & Co.", "V": "Visa Inc.",
        "JNJ": "Johnson & Johnson", "WMT": "Walmart Inc.", "PG": "Procter & Gamble Co.",
        "DIS": "The Walt Disney Company", "NFLX": "Netflix Inc.", "ADBE": "Adobe Inc.",
        "PYPL": "PayPal Holdings Inc.", "INTC": "Intel Corporation", "CSCO": "Cisco Systems Inc.",
        "PFE": "Pfizer Inc.", "XOM": "Exxon Mobil Corporation", "BAC": "Bank of America Corp",
        "KO": "The Coca-Cola Company", "PEP": "PepsiCo Inc.", "NKE": "Nike Inc.",
        "RELIANCE.NS": "Reliance Industries Ltd", "TCS.NS": "Tata Consultancy Services Ltd",
        "HDFCBANK.NS": "HDFC Bank Ltd", "INFY.NS": "Infosys Ltd", "ICICIBANK.NS": "ICICI Bank Ltd",
        "WIPRO.NS": "Wipro Ltd", "BAJFINANCE.NS": "Bajaj Finance Ltd",
    }
    q = query.upper()
    results = [
        {"symbol": s, "name": n, "match_type": "symbol" if q in s else "name"}
        for s, n in stock_db.items() if q in s or q in n.upper()
    ]
    results.sort(key=lambda x: (0 if x['match_type'] == 'symbol' and x['symbol'] == q else 1 if x['match_type'] == 'symbol' else 2, x['symbol']))
    return {"results": results[:15]}

@app.get("/api/cache/invalidate/{symbol}")
async def invalidate_cache(symbol: str):
    symbol = symbol.upper().strip()
    invalidate_symbol_cache(symbol)
    return {"status": "ok", "symbol": symbol, "message": "Cache invalidated"}

@app.get("/api/debug/{symbol}")
async def debug_stock(symbol: str):
    try:
        symbol = symbol.upper().strip()
        result = {
            "symbol": symbol, 
            "timestamp": datetime.now().isoformat(), 
            "hybrid_engine": hybrid_engine.get_stats(),
            "tests": []
        }
        
        # Test hybrid engine quote
        quote = await hybrid_engine.get_quote(symbol)
        result["tests"].append({
            "name": "hybrid_quote",
            "success": bool(quote and quote.get('price')),
            "data": quote
        })
        
        # Test hybrid engine historical
        hist = await hybrid_engine.get_historical(symbol, "1mo")
        result["tests"].append({
            "name": "hybrid_historical",
            "success": bool(hist and len(hist) > 0),
            "count": len(hist) if hist else 0
        })
        
        # Test hybrid engine company info
        info = await hybrid_engine.get_company_info(symbol)
        result["tests"].append({
            "name": "hybrid_company",
            "success": bool(info),
            "company": (info.get('longName') or info.get('shortName')) if info else None
        })
        
        return result
    except Exception as e:
        return {"symbol": symbol, "error": str(e), "timestamp": datetime.now().isoformat()}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True, log_level="info")