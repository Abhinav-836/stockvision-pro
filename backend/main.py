# backend/main.py — FIXED: yFinance fills missing fundamentals only

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
import pandas as pd
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

# ============= YFINANCE FUNDAMENTALS FETCHER =============

async def fetch_yf_fundamentals(symbol: str) -> Dict:
    """Fetch ONLY missing fundamental data from yFinance"""
    try:
        if yf_rate_limiter.is_blocked():
            return {}
        
        await yf_rate_limiter.acquire()
        loop = asyncio.get_event_loop()
        stock = await asyncio.wait_for(loop.run_in_executor(None, yf.Ticker, symbol), timeout=8)
        info = await asyncio.wait_for(loop.run_in_executor(None, lambda: stock.info or {}), timeout=8)
        
        if not info:
            return {}
        
        # Only extract the fundamental metrics we need
        fundamentals = {}
        
        if info.get('trailingPE') is not None:
            fundamentals['trailingPE'] = float(info['trailingPE'])
        if info.get('priceToBook') is not None:
            fundamentals['priceToBook'] = float(info['priceToBook'])
        if info.get('trailingEps') is not None:
            fundamentals['trailingEps'] = float(info['trailingEps'])
        if info.get('returnOnEquity') is not None:
            fundamentals['returnOnEquity'] = float(info['returnOnEquity'])
        if info.get('returnOnAssets') is not None:
            fundamentals['returnOnAssets'] = float(info['returnOnAssets'])
        if info.get('debtToEquity') is not None:
            fundamentals['debtToEquity'] = float(info['debtToEquity'])
        if info.get('dividendYield') is not None:
            fundamentals['dividendYield'] = float(info['dividendYield'])
        if info.get('averageVolume') is not None:
            fundamentals['averageVolume'] = float(info['averageVolume'])
        if info.get('fiftyTwoWeekHigh') is not None:
            fundamentals['fiftyTwoWeekHigh'] = float(info['fiftyTwoWeekHigh'])
        if info.get('fiftyTwoWeekLow') is not None:
            fundamentals['fiftyTwoWeekLow'] = float(info['fiftyTwoWeekLow'])
        if info.get('marketCap') is not None:
            fundamentals['marketCap'] = float(info['marketCap'])
        if info.get('sharesOutstanding') is not None:
            fundamentals['sharesOutstanding'] = float(info['sharesOutstanding'])
        
        logger.debug(f"Fetched {len(fundamentals)} fundamentals from yFinance for {symbol}")
        return fundamentals
    except asyncio.TimeoutError:
        logger.debug(f"yFinance fundamentals timeout for {symbol}")
        return {}
    except Exception as e:
        logger.debug(f"Could not fetch fundamentals from yFinance for {symbol}: {type(e).__name__}")
        return {}

# ============= OPTIMIZED HYBRID DATA ENGINE =============

class HybridDataEngine:
    """
    Hybrid data provider with cascading fallback:
    Finnhub (fastest real-time) → Alpha Vantage → yFinance (ultimate fallback)
    """
    
    def __init__(self):
        # Finnhub (Priority 1 - Fastest real-time)
        self.fh_api_key = os.getenv("FINNHUB_API_KEY")
        self.fh_enabled = bool(self.fh_api_key) and FINNHUB_AVAILABLE
        self.fh_client = finnhub.Client(api_key=self.fh_api_key) if self.fh_enabled else None
        self.fh_calls = 0
        self.fh_success = 0
        self.fh_calls_minute = []
        self.fh_historical_available = True

        # Alpha Vantage (Priority 2 - Best fundamentals)
        self.av_api_key = os.getenv("ALPHA_VANTAGE_API_KEY")
        self.av_base_url = "https://www.alphavantage.co/query"
        self.av_enabled = bool(self.av_api_key)
        self.av_calls = 0
        self.av_success = 0
        self.av_calls_minute = []
        self.av_calls_day = []
        self.av_day_reset = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        self.av_daily_limit = int(os.getenv("ALPHA_VANTAGE_DAILY_LIMIT", 25))

        # Cache
        self.cache = {}
        self.quote_cache_ttl = 30
        self.historical_cache_ttl = 300
        
        # Stats
        self.yf_calls = 0
        self.yf_success = 0
        
        logger.info(f"🚀 Hybrid Engine initialized: FH={self.fh_enabled}, AV={self.av_enabled}")
    
    # ========================================================================
    # FINNHUB METHODS
    # ========================================================================
    
    def _can_call_fh(self) -> bool:
        now = time.time()
        self.fh_calls_minute = [t for t in self.fh_calls_minute if now - t < 60]
        return len(self.fh_calls_minute) < 60
    
    def _record_fh_call(self):
        self.fh_calls += 1
        self.fh_calls_minute.append(time.time())
    
    async def _fetch_fh_quote(self, symbol: str) -> Optional[Dict]:
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
        if not self.fh_enabled or not self._can_call_fh():
            return None
        
        try:
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
            else:
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
            logger.warning(f"Finnhub historical error for {symbol}: {type(e).__name__}: {e}")
        return None
    
    async def _fetch_fh_company_info(self, symbol: str) -> Optional[Dict]:
        if not self.fh_enabled or not self._can_call_fh():
            return None
        
        try:
            loop = asyncio.get_event_loop()
            profile = await asyncio.wait_for(
                loop.run_in_executor(None, lambda: self.fh_client.company_profile2(symbol=symbol)),
                timeout=8
            )
            self._record_fh_call()
            
            if profile:
                self.fh_success += 1
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
    # ALPHA VANTAGE METHODS
    # ========================================================================
    
    def _can_call_av(self) -> bool:
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
    
    def _record_av_call(self):
        now = time.time()
        self.av_calls += 1
        self.av_calls_minute.append(now)
        self.av_calls_day.append(now)
    
    async def _fetch_av_quote(self, symbol: str) -> Optional[Dict]:
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
                    if any(k in data for k in ("Error Message", "Note", "Information")):
                        logger.warning(f"Alpha Vantage quote rejected for {symbol}: {data}")
        except Exception as e:
            logger.warning(f"Alpha Vantage quote error for {symbol}: {type(e).__name__}: {e}")
        return None
    
    async def _fetch_av_historical(self, symbol: str, period: str = "1mo") -> Optional[List[Dict]]:
        if not self.av_enabled or not self._can_call_av():
            return None
        
        output_size = "compact" if period in ["1d", "5d", "1mo"] else "full"
        
        try:
            params = {
                "function": "TIME_SERIES_DAILY",
                "symbol": symbol,
                "outputsize": output_size,
                "apikey": self.av_api_key
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(self.av_base_url, params=params, timeout=12) as response:
                    data = await response.json()
                    self._record_av_call()
                    
                    if "Error Message" in data:
                        logger.warning(f"Alpha Vantage historical rejected for {symbol}: {data.get('Error Message')}")
                        return None
                    if "Note" in data:
                        logger.warning(f"Alpha Vantage historical rate-limited for {symbol}: {data.get('Note')}")
                        return None
                    if "Information" in data:
                        logger.warning(f"Alpha Vantage historical rejected for {symbol}: {data.get('Information')}")
                        return None
                    
                    time_series = data.get("Time Series (Daily)", {})
                    if time_series:
                        result = []
                        for date, values in sorted(time_series.items(), reverse=True)[:100]:
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
        if not self.av_enabled or not self._can_call_av():
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
                    
                    if data and "Symbol" in data:
                        self.av_success += 1
                        result = {
                            "symbol": data.get("Symbol"),
                            "company_name": data.get("Name"),
                            "sector": data.get("Sector"),
                            "industry": data.get("Industry"),
                            "market_cap": float(data.get("MarketCapitalization", 0)),
                            "pe_ratio": float(data.get("PERatio", 0)),
                            "pb_ratio": float(data.get("PriceToBookRatio", 0)),
                            "roe": float(data.get("ReturnOnEquityTTM", "0").replace("%", "")),
                            "roa": float(data.get("ReturnOnAssetsTTM", "0").replace("%", "")),
                            "dividend_yield": float(data.get("DividendYield", "0").replace("%", "")),
                            "eps": float(data.get("EPS", 0)),
                        }
                        if data.get("DebtToEquity") not in (None, "None", "-", ""):
                            result["debt_to_equity"] = float(data["DebtToEquity"])
                        if data.get("QuarterlyRevenueGrowthYOY") not in (None, "None", "-", ""):
                            result["revenue_growth"] = float(data["QuarterlyRevenueGrowthYOY"]) * 100
                        return result
        except Exception as e:
            logger.warning(f"Alpha Vantage company info error for {symbol}: {type(e).__name__}: {e}")
        return None
    
    # ========================================================================
    # YFINANCE METHODS (Fallback)
    # ========================================================================
    
    async def _fetch_yf_quote(self, symbol: str) -> Optional[Dict]:
        if yf_rate_limiter.is_blocked():
            return None
            
        try:
            await yf_rate_limiter.acquire()
            loop = asyncio.get_event_loop()
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
            yf_rate_limiter.record_failure()
        except Exception as e:
            logger.warning(f"yFinance quote error for {symbol}: {type(e).__name__}: {e}")
            yf_rate_limiter.record_failure()
        return None
    
    async def _fetch_yf_historical(self, symbol: str, period: str = "1mo", interval: str = "1d") -> Optional[List[Dict]]:
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
            yf_rate_limiter.record_failure()
        except Exception as e:
            logger.warning(f"yFinance historical error for {symbol}: {type(e).__name__}: {e}")
            yf_rate_limiter.record_failure()
        return None
    
    async def _fetch_yf_company_info(self, symbol: str) -> Optional[Dict]:
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
            logger.warning(f"yFinance company info error for {symbol}: {type(e).__name__}: {e}")
            yf_rate_limiter.record_failure()
        return None
    
    # ========================================================================
    # PUBLIC METHODS WITH CASCADING FALLBACK
    # ========================================================================
    
    async def get_quote(self, symbol: str) -> Optional[Dict]:
        cache_key = f"quote:{symbol}"
        if cache_key in self.cache:
            cached, ts = self.cache[cache_key]
            if time.time() - ts < self.quote_cache_ttl:
                return cached
        
        result = await self._fetch_fh_quote(symbol)
        if result:
            self.cache[cache_key] = (result, time.time())
            return result
        
        result = await self._fetch_av_quote(symbol)
        if result:
            self.cache[cache_key] = (result, time.time())
            return result
        
        result = await self._fetch_yf_quote(symbol)
        if result:
            self.cache[cache_key] = (result, time.time())
            return result
        
        return None
    
    async def get_historical(self, symbol: str, period: str = "1mo", interval: str = "1d") -> Optional[List[Dict]]:
        cache_key = f"hist:{symbol}:{period}:{interval}"
        if cache_key in self.cache:
            cached, ts = self.cache[cache_key]
            if time.time() - ts < self.historical_cache_ttl:
                return cached
        
        result = await self._fetch_fh_historical(symbol, period)
        if result:
            self.cache[cache_key] = (result, time.time())
            return result
        
        result = await self._fetch_av_historical(symbol, period)
        if result:
            self.cache[cache_key] = (result, time.time())
            return result
        
        result = await self._fetch_yf_historical(symbol, period, interval)
        if result:
            self.cache[cache_key] = (result, time.time())
            return result
        
        return None
    
    async def get_company_info(self, symbol: str) -> Optional[Dict]:
        result = await self._fetch_av_company_info(symbol)
        if result:
            return _map_av_fh_company_info_to_yf_schema(result)
        
        result = await self._fetch_fh_company_info(symbol)
        if result:
            return _map_av_fh_company_info_to_yf_schema(result)
        
        result = await self._fetch_yf_company_info(symbol)
        if result:
            return result
        
        return None
    
    async def get_indices(self, symbols: List[str]) -> List[Dict]:
        results = []
        for symbol in symbols:
            try:
                quote = await self._fetch_fh_quote(symbol)
                if quote:
                    results.append({
                        "symbol": symbol,
                        "name": self._get_index_name(symbol),
                        "value": quote.get("price", 0),
                        "change": quote.get("change_percent", 0),
                        "source": "Finnhub"
                    })
                    continue
                
                quote = await self._fetch_yf_quote(symbol)
                if quote:
                    results.append({
                        "symbol": symbol,
                        "name": self._get_index_name(symbol),
                        "value": quote.get("price", 0),
                        "change": quote.get("change_percent", 0),
                        "source": "yFinance"
                    })
            except Exception as e:
                logger.warning(f"Failed to fetch index {symbol}: {e}")
        
        return results
    
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
            "cache_size": len(self.cache)
        }


# ============= RATE LIMITER =============
class YFinanceRateLimiter:
    def __init__(self, max_calls_per_minute=25):
        self.calls = []
        self.max_calls = max_calls_per_minute
        self.lock = asyncio.Lock()
        self.consecutive_failures = 0
        self.failure_threshold = 5
        self.cooldown_seconds = 300
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
            if websocket in self.subscriptions[symbol]:
                self.subscriptions[symbol].remove(websocket)

    async def subscribe(self, websocket: WebSocket, symbol: str):
        if symbol not in self.subscriptions:
            self.subscriptions[symbol] = []
        if websocket not in self.subscriptions[symbol]:
            self.subscriptions[symbol].append(websocket)

    async def broadcast_to_symbol(self, symbol: str, message: dict):
        if symbol in self.subscriptions:
            dead = []
            for connection in self.subscriptions[symbol]:
                try:
                    await connection.send_json(message)
                except Exception:
                    dead.append(connection)
            for d in dead:
                self.subscriptions[symbol].remove(d)

    async def broadcast_all(self, message: dict):
        dead = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                dead.append(connection)
        for d in dead:
            self.active_connections.remove(d)

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
last_good_stock_cache = LRUCache(max_size=config.MAX_CACHE_SIZE, ttl=21600)
last_good_chart_cache = LRUCache(max_size=config.MAX_CACHE_SIZE, ttl=21600)
yf_rate_limiter = YFinanceRateLimiter(max_calls_per_minute=25)

request_counts = defaultdict(list)

# ============= FASTAPI APP =============
app = FastAPI(
    title=config.API_TITLE,
    version=config.API_VERSION,
    description="AI-powered stock analysis with Optimized Hybrid Engine",
    docs_url="/api/docs",
    redoc_url="/api/redoc"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    client_ip = request.client.host if request.client else "unknown"
    now = time.time()
    request_counts[client_ip] = [t for t in request_counts[client_ip] if now - t < 60]
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
class StockRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=15)

    @validator('symbol')
    def validate_symbol(cls, v):
        v = v.upper().strip()
        if not v:
            raise ValueError('Symbol cannot be empty')
        if not re.match(r'^[A-Z0-9]{1,10}(\.[A-Z]{2,3})?$', v):
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
            if not re.match(r'^[A-Z0-9]{1,10}(\.[A-Z]{2,3})?$', symbol):
                raise ValueError(f'Invalid symbol: {symbol}')
            cleaned.append(symbol)
        if len(cleaned) != len(set(cleaned)):
            raise ValueError('Duplicate symbols detected')
        return cleaned

# ============= WEBSOCKET =============
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            try:
                message = json.loads(data)
                message_type = message.get('type')
                if message_type == 'subscribe':
                    symbol = message.get('symbol')
                    if symbol:
                        await manager.subscribe(websocket, symbol)
                        await websocket.send_json({
                            "type": "subscribed",
                            "symbol": symbol,
                            "status": "success"
                        })
                elif message_type == 'unsubscribe':
                    symbol = message.get('symbol')
                    if symbol and symbol in manager.subscriptions:
                        if websocket in manager.subscriptions[symbol]:
                            manager.subscriptions[symbol].remove(websocket)
            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "message": "Invalid JSON"})
    except WebSocketDisconnect:
        manager.disconnect(websocket)

# ============= BACKGROUND TASKS =============
async def _fetch_indices_internal() -> list:
    indices_config = [
        '^GSPC', '^IXIC', '^DJI', '^RUT', '^VIX',
        '^NSEI', '^BSESN', 'BTC-USD', 'GC=F', 'CL=F'
    ]
    return await hybrid_engine.get_indices(indices_config)

async def market_updater():
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
        await asyncio.sleep(60)

async def price_updater():
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
                            quote = await hybrid_engine.get_quote(symbol)
                            
                            if quote and quote.get('price'):
                                current_price = quote['price']
                                change = quote.get('change_percent', 0)
                                
                                last_price = last_prices.get(symbol, current_price)
                                if abs(current_price - last_price) > 0.05 or abs(change) > 0.5:
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
                    await asyncio.sleep(0.5)
            update_interval = 5
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
    """Fetch stock data using hybrid engine with yFinance fundamentals fallback"""
    
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
        
        # Use hybrid engine for historical
        hist_data = await hybrid_engine.get_historical(symbol, "1mo")
        
        # Get company info (priority: Alpha Vantage → Finnhub → yFinance)
        company_info = await hybrid_engine.get_company_info(symbol)
        
        # If we have quote data, convert to yFinance-like format
        if quote:
            class MockStock:
                def __init__(self, info_dict):
                    self.info = info_dict
                    
            info = {
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
            
            # Add company info if available
            if company_info:
                info.update(company_info)
            
            # ================================================================
            # FIX: Fetch missing fundamentals from yFinance
            # ================================================================
            # Check if we're missing key fundamental metrics
            missing_fundamentals = False
            for key in ['trailingPE', 'priceToBook', 'trailingEps', 'returnOnEquity', 
                        'returnOnAssets', 'debtToEquity', 'dividendYield', 'averageVolume']:
                if key not in info or info.get(key) is None:
                    missing_fundamentals = True
                    break
            
            if missing_fundamentals:
                logger.info(f"Missing fundamentals for {symbol}, fetching from yFinance...")
                yf_fundamentals = await fetch_yf_fundamentals(symbol)
                if yf_fundamentals:
                    # Merge: only add if field doesn't exist or is None/0
                    for key, value in yf_fundamentals.items():
                        if key not in info or info.get(key) in (None, 0, 'N/A'):
                            info[key] = value
                    logger.info(f"Added {len(yf_fundamentals)} fundamentals from yFinance for {symbol}")
            
            stock = MockStock(info)
            
            # Convert historical data to DataFrame
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

        # Ultimate fallback to yFinance
        await yf_rate_limiter.acquire()
        loop = asyncio.get_event_loop()
        try:
            stock = await asyncio.wait_for(loop.run_in_executor(None, yf.Ticker, symbol), timeout=8)
            info = await asyncio.wait_for(loop.run_in_executor(None, lambda: stock.info or {}), timeout=8)
            hist = await asyncio.wait_for(loop.run_in_executor(None, lambda: stock.history(period="1mo")), timeout=10)
        except asyncio.TimeoutError:
            logger.warning(f"yFinance ultimate fallback timed out for {symbol}")
            return None, {}, None

        if hist is not None and not hist.empty:
            result = (stock, info, hist)
            if use_cache:
                stock_cache.set(cache_key, result)
            return result

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

def build_stock_response(symbol: str, stock, info: Dict, hist) -> Dict:
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
        news             = get_latest_news(symbol)

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

        result = await fetch_stock_data(symbol, use_cache=False)
        if result and result[0] is not None and result[2] is not None:
            stock, info, hist = result
            response_data = build_stock_response(symbol, stock, info, hist)
            if use_cache:
                stock_cache.set(cache_key, response_data)
            last_good_stock_cache.set(symbol, response_data)
            return response_data

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

        last_good = last_good_chart_cache.get(cache_key)
        if last_good:
            logger.warning(f"Live chart fetch failed for {symbol} — serving last known-good real chart data")
            return last_good

        logger.info(f"Using synthetic chart data for {symbol} ({period}) — live sources unavailable")
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

@app.post("/api/compare")
async def compare_stocks(request: CompareRequest):
    try:
        symbols = request.symbols
        tasks = [fetch_stock_data(symbol) for symbol in symbols]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        stocks_data = []
        failed = []
        for i, result in enumerate(results):
            symbol = symbols[i]
            if isinstance(result, Exception) or not result or result[0] is None:
                failed.append(f"{symbol}: Data unavailable")
                stocks_data.append(get_fallback_stock_data(symbol))
                continue
            try:
                stock, info, hist = result
                stocks_data.append(build_stock_response(symbol, stock, info, hist))
            except Exception as e:
                failed.append(f"{symbol}: {e}")
                stocks_data.append(get_fallback_stock_data(symbol))

        valid_pe  = [s for s in stocks_data if s.get('pe_ratio')       is not None]
        valid_roe = [s for s in stocks_data if s.get('roe')            is not None]
        valid_div = [s for s in stocks_data if s.get('dividend_yield') is not None]
        valid_vol = [s for s in stocks_data if s.get('volatility')     is not None]

        comparison_data = {
            "ai_top_pick":   max(stocks_data, key=lambda x: x.get('ai_score', 0))['symbol'],
            "best_value":    min(valid_pe,  key=lambda x: x.get('pe_ratio', float('inf')))['symbol'] if valid_pe  else "N/A",
            "best_dividend": max(valid_div, key=lambda x: x.get('dividend_yield', 0))['symbol']      if valid_div else "N/A",
            "lowest_risk":   min(valid_vol, key=lambda x: x.get('volatility', float('inf')))['symbol'] if valid_vol else "N/A",
            "average_pe":    round(np.mean([s['pe_ratio'] for s in valid_pe]),  2) if valid_pe  else 0,
            "average_roe":   round(np.mean([s['roe'] for s in valid_roe]),      2) if valid_roe else 0,
            "average_debt":  round(np.mean([s.get('debt_to_equity', 0) or 0 for s in stocks_data]), 2),
            "failed_symbols": failed,
        }
        return {"stocks": stocks_data, "comparison": comparison_data}

    except Exception as e:
        logger.error(f"Error comparing stocks: {e}")
        raise HTTPException(status_code=500, detail="Error comparing stocks")

@app.post("/api/ai/compare")
async def ai_compare_stocks(request: CompareRequest, req: Request = None):
    try:
        symbols = request.symbols
        user_id = req.client.host if req and req.client else "anonymous"
        tasks = [fetch_stock_data(symbol) for symbol in symbols]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        stocks_data = []
        failed = []
        for i, result in enumerate(results):
            if isinstance(result, Exception) or not result or result[0] is None:
                failed.append(symbols[i])
                stocks_data.append(get_fallback_stock_data(symbols[i]))
                continue
            stock, info, hist = result
            try:
                stocks_data.append(build_stock_response(symbols[i], stock, info, hist))
            except Exception:
                stocks_data.append(get_fallback_stock_data(symbols[i]))

        ai_analysis = await ai_service.analyze_stock_comparison(stocks_data, user_id=user_id)
        return {
            "success": True,
            "stocks": stocks_data,
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
async def get_ai_thesis(symbol: str, req: Request = None):
    try:
        symbol = symbol.upper().strip()
        user_id = req.client.host if req and req.client else "anonymous"
        result = await fetch_stock_data(symbol)
        if result and result[0] is not None and result[2] is not None:
            stock, info, hist = result
            stock_data = build_stock_response(symbol, stock, info, hist)
        else:
            stock_data = get_fallback_stock_data(symbol)
        news = get_latest_news(symbol)
        thesis = await ai_service.generate_investment_thesis(stock_data, news, user_id=user_id)
        return {"success": True, "symbol": symbol, "thesis": thesis, "timestamp": datetime.now().isoformat()}
    except Exception as e:
        logger.error(f"Error generating thesis: {e}")
        return {"success": False, "error": str(e)}

@app.post("/api/ai/question")
async def ask_ai_question(request: dict, req: Request = None):
    try:
        question = request.get("question")
        symbol   = request.get("symbol")
        user_id  = req.client.host if req and req.client else "anonymous"
        if not question:
            return {"success": False, "error": "Question is required"}
        stock_data = None
        if symbol:
            try:
                result = await fetch_stock_data(symbol)
                if result and result[0] is not None:
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
async def analyze_sentiment(request: dict, req: Request = None):
    try:
        symbols = request.get("symbols", [])
        user_id = req.client.host if req and req.client else "anonymous"
        if not symbols:
            return {"success": False, "error": "Symbols required"}
        news_data = {symbol: get_latest_news(symbol, max_news=3) for symbol in symbols}
        sentiment = await ai_service.get_market_sentiment(symbols, news_data, user_id=user_id)
        return {"success": True, "sentiment": sentiment, "timestamp": datetime.now().isoformat()}
    except Exception as e:
        logger.error(f"Error analyzing sentiment: {e}")
        return {"success": False, "error": str(e)}

@app.get("/api/market-indices")
async def get_market_indices(use_cache: bool = True):
    cache_key = "market:indices"
    if use_cache:
        cached = stock_cache.get(cache_key)
        if cached:
            ts = cached.get("_timestamp", 0) if isinstance(cached, dict) else 0
            if time.time() - ts < 120:
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
        try:
            quote = await hybrid_engine.get_quote(symbol)
            company_info = await hybrid_engine.get_company_info(symbol)
            
            if quote and quote.get('price'):
                return {
                    "symbol": symbol,
                    "name": company_info.get('company_name', symbol) if company_info else symbol,
                    "price": quote.get('price', 0),
                    "change": quote.get('change_percent', 0),
                    "volume": quote.get('volume', 0),
                    "market_cap": company_info.get('market_cap', 0) if company_info else 0,
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
        
        quote = await hybrid_engine.get_quote(symbol)
        result["tests"].append({
            "name": "hybrid_quote",
            "success": bool(quote and quote.get('price')),
            "data": quote
        })
        
        hist = await hybrid_engine.get_historical(symbol, "1mo")
        result["tests"].append({
            "name": "hybrid_historical",
            "success": bool(hist and len(hist) > 0),
            "count": len(hist) if hist else 0
        })
        
        info = await hybrid_engine.get_company_info(symbol)
        result["tests"].append({
            "name": "hybrid_company",
            "success": bool(info),
            "company": info.get('company_name') if info else None
        })
        
        # Also test yFinance fundamentals fetch
        yf_fund = await fetch_yf_fundamentals(symbol)
        result["tests"].append({
            "name": "yfinance_fundamentals",
            "success": bool(yf_fund),
            "keys": list(yf_fund.keys()) if yf_fund else []
        })
        
        return result
    except Exception as e:
        return {"symbol": symbol, "error": str(e), "timestamp": datetime.now().isoformat()}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True, log_level="info")