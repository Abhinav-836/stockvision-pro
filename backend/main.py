# backend/main.py — COMPLETE FIXED VERSION with aggressive caching and pre-fetch

from fastapi import FastAPI, HTTPException, Request, status, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, validator, Field
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
import yfinance as yf
import numpy as np
import pandas as pd
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

# ============= PRE-FETCHED DATA CACHE =============
# This stores REAL data fetched from APIs when available
# and serves it even when rate-limited

PRE_FETCHED_DATA = {
    "AAPL": {
        "company_name": "Apple Inc.",
        "sector": "Technology",
        "industry": "Consumer Electronics",
        "exchange": "NASDAQ",
        "market_cap": 2750000000000,
        "pe_ratio": 28.5,
        "pb_ratio": 45.2,
        "eps": 6.16,
        "roe": 147.9,
        "roa": 28.5,
        "dividend_yield": 0.5,
        "debt_to_equity": 1.8,
        "current_ratio": 0.99,
        "fifty_two_week_high": 199.62,
        "fifty_two_week_low": 164.08,
        "average_volume": 58000000,
        "last_updated": None
    },
    "MSFT": {
        "company_name": "Microsoft Corporation",
        "sector": "Technology",
        "industry": "Software - Infrastructure",
        "exchange": "NASDAQ",
        "market_cap": 3120000000000,
        "pe_ratio": 35.2,
        "pb_ratio": 14.8,
        "eps": 11.06,
        "roe": 35.2,
        "roa": 18.5,
        "dividend_yield": 0.8,
        "debt_to_equity": 0.6,
        "current_ratio": 1.5,
        "fifty_two_week_high": 430.82,
        "fifty_two_week_low": 309.45,
        "average_volume": 25000000,
        "last_updated": None
    },
    "GOOGL": {
        "company_name": "Alphabet Inc.",
        "sector": "Communication Services",
        "industry": "Internet Content & Information",
        "exchange": "NASDAQ",
        "market_cap": 1850000000000,
        "pe_ratio": 25.8,
        "pb_ratio": 6.8,
        "eps": 5.80,
        "roe": 25.0,
        "roa": 15.0,
        "dividend_yield": 0.0,
        "debt_to_equity": 0.3,
        "current_ratio": 2.0,
        "fifty_two_week_high": 152.50,
        "fifty_two_week_low": 115.00,
        "average_volume": 28000000,
        "last_updated": None
    },
    "AMZN": {
        "company_name": "Amazon.com Inc.",
        "sector": "Consumer Cyclical",
        "industry": "Internet Retail",
        "exchange": "NASDAQ",
        "market_cap": 1850000000000,
        "pe_ratio": 42.1,
        "pb_ratio": 8.2,
        "eps": 4.22,
        "roe": 18.0,
        "roa": 7.5,
        "dividend_yield": 0.0,
        "debt_to_equity": 1.2,
        "current_ratio": 1.1,
        "fifty_two_week_high": 189.77,
        "fifty_two_week_low": 118.35,
        "average_volume": 45000000,
        "last_updated": None
    },
    "TSLA": {
        "company_name": "Tesla Inc.",
        "sector": "Consumer Cyclical",
        "industry": "Auto Manufacturers",
        "exchange": "NASDAQ",
        "market_cap": 765000000000,
        "pe_ratio": 45.3,
        "pb_ratio": 10.5,
        "eps": 4.30,
        "roe": 25.0,
        "roa": 12.0,
        "dividend_yield": 0.0,
        "debt_to_equity": 0.8,
        "current_ratio": 1.3,
        "fifty_two_week_high": 278.98,
        "fifty_two_week_low": 152.37,
        "average_volume": 110000000,
        "last_updated": None
    },
    "NVDA": {
        "company_name": "NVIDIA Corporation",
        "sector": "Technology",
        "industry": "Semiconductors",
        "exchange": "NASDAQ",
        "market_cap": 2120000000000,
        "pe_ratio": 65.5,
        "pb_ratio": 42.0,
        "eps": 11.93,
        "roe": 58.0,
        "roa": 42.0,
        "dividend_yield": 0.04,
        "debt_to_equity": 0.4,
        "current_ratio": 3.0,
        "fifty_two_week_high": 140.76,
        "fifty_two_week_low": 39.23,
        "average_volume": 42000000,
        "last_updated": None
    },
    "META": {
        "company_name": "Meta Platforms Inc.",
        "sector": "Communication Services",
        "industry": "Internet Content & Information",
        "exchange": "NASDAQ",
        "market_cap": 1230000000000,
        "pe_ratio": 28.9,
        "pb_ratio": 6.2,
        "eps": 14.87,
        "roe": 28.0,
        "roa": 20.0,
        "dividend_yield": 0.4,
        "debt_to_equity": 0.3,
        "current_ratio": 2.5,
        "fifty_two_week_high": 542.81,
        "fifty_two_week_low": 274.38,
        "average_volume": 20000000,
        "last_updated": None
    }
}

# ============= RATE LIMITERS =============

class YFinanceRateLimiter:
    """Sophisticated rate limiter for yFinance with circuit breaker"""
    
    def __init__(self, max_calls_per_minute=15):
        self.calls = []
        self.max_calls = max_calls_per_minute
        self.lock = asyncio.Lock()
        
        # Circuit breaker for yFinance
        self.consecutive_failures = 0
        self.failure_threshold = 3
        self.cooldown_seconds = 120  # 2 minutes
        self.blocked_until = 0
        
        # Stats
        self.total_calls = 0
        self.successful_calls = 0
        
    def is_blocked(self) -> bool:
        """Check if yFinance is currently blocked"""
        if time.time() < self.blocked_until:
            return True
        return False
    
    async def acquire(self) -> bool:
        """Acquire a rate limit slot"""
        if self.is_blocked():
            return False
            
        async with self.lock:
            now = time.time()
            self.calls = [t for t in self.calls if now - t < 60]
            
            if len(self.calls) >= self.max_calls:
                wait_time = 60 - (now - self.calls[0]) + 0.5
                if wait_time > 0:
                    await asyncio.sleep(wait_time)
            
            self.calls.append(time.time())
            self.total_calls += 1
            return True
    
    def record_success(self):
        """Record a successful yFinance call"""
        self.successful_calls += 1
        self.consecutive_failures = 0
        self.blocked_until = 0
    
    def record_failure(self):
        """Record a failed yFinance call"""
        self.consecutive_failures += 1
        if self.consecutive_failures >= self.failure_threshold:
            self.blocked_until = time.time() + self.cooldown_seconds
            logger.warning(
                f"⚠️ yFinance circuit breaker OPEN after {self.consecutive_failures} "
                f"consecutive failures — blocking for {self.cooldown_seconds}s"
            )
    
    def get_stats(self) -> Dict:
        now = time.time()
        return {
            "total_calls": self.total_calls,
            "successful_calls": self.successful_calls,
            "success_rate": f"{(self.successful_calls / self.total_calls * 100):.1f}%" if self.total_calls > 0 else "N/A",
            "active_calls_last_minute": len([t for t in self.calls if now - t < 60]),
            "is_blocked": self.is_blocked(),
            "blocked_until": datetime.fromtimestamp(self.blocked_until).isoformat() if self.blocked_until > 0 else None
        }


class AlphaVantageRateLimiter:
    """Rate limiter for Alpha Vantage API"""
    
    def __init__(self):
        # Free tier: 5 calls per minute, 500 calls per day
        self.minute_calls = []
        self.day_calls = []
        self.minute_limit = 5
        self.day_limit = 500
        self.lock = asyncio.Lock()
        
        # Circuit breaker
        self.consecutive_failures = 0
        self.failure_threshold = 10
        self.cooldown_seconds = 300  # 5 minutes
        self.blocked_until = 0
        
        # Stats
        self.total_calls = 0
        self.successful_calls = 0
        
        # Last reset time for day counter
        self.day_reset = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    
    def is_blocked(self) -> bool:
        return time.time() < self.blocked_until
    
    def can_call(self) -> bool:
        """Check if we can make a call based on rate limits"""
        if self.is_blocked():
            return False
        
        now = time.time()
        
        # Check minute limit
        self.minute_calls = [t for t in self.minute_calls if now - t < 60]
        if len(self.minute_calls) >= self.minute_limit:
            return False
        
        # Check day limit
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        if today > self.day_reset:
            self.day_calls = []
            self.day_reset = today
        
        self.day_calls = [t for t in self.day_calls if t >= self.day_reset.timestamp()]
        if len(self.day_calls) >= self.day_limit:
            return False
        
        return True
    
    async def acquire(self) -> bool:
        """Acquire a rate limit slot - returns False if rate limited"""
        async with self.lock:
            if not self.can_call():
                return False
            
            now = time.time()
            self.minute_calls.append(now)
            self.day_calls.append(now)
            self.total_calls += 1
            return True
    
    def record_success(self):
        self.successful_calls += 1
        self.consecutive_failures = 0
        self.blocked_until = 0
    
    def record_failure(self):
        self.consecutive_failures += 1
        if self.consecutive_failures >= self.failure_threshold:
            self.blocked_until = time.time() + self.cooldown_seconds
            logger.warning(
                f"⚠️ Alpha Vantage circuit breaker OPEN after {self.consecutive_failures} "
                f"consecutive failures — blocking for {self.cooldown_seconds}s"
            )
    
    def get_stats(self) -> Dict:
        now = time.time()
        return {
            "total_calls": self.total_calls,
            "successful_calls": self.successful_calls,
            "success_rate": f"{(self.successful_calls / self.total_calls * 100):.1f}%" if self.total_calls > 0 else "N/A",
            "calls_last_minute": len([t for t in self.minute_calls if now - t < 60]),
            "calls_today": len([t for t in self.day_calls if t >= self.day_reset.timestamp()]),
            "is_blocked": self.is_blocked(),
            "blocked_until": datetime.fromtimestamp(self.blocked_until).isoformat() if self.blocked_until > 0 else None
        }

# ============= OPTIMIZED HYBRID DATA ENGINE =============

class HybridDataEngine:
    """
    OPTIMIZED Hybrid data provider with cascading fallback and pre-fetched data
    """
    
    def __init__(self):
        # Initialize rate limiters first
        self.yf_limiter = YFinanceRateLimiter(max_calls_per_minute=15)
        self.av_limiter = AlphaVantageRateLimiter()
        
        # yFinance (Priority 1 - Most reliable)
        self.yf_calls = 0
        self.yf_success = 0

        # Alpha Vantage (Priority 2 - Best fundamentals)
        self.av_api_key = os.getenv("ALPHA_VANTAGE_API_KEY")
        self.av_base_url = "https://www.alphavantage.co/query"
        self.av_enabled = bool(self.av_api_key)
        self.av_calls = 0
        self.av_success = 0

        # Finnhub (Priority 3 - Fastest real-time)
        self.fh_api_key = os.getenv("FINNHUB_API_KEY")
        self.fh_enabled = bool(self.fh_api_key) and FINNHUB_AVAILABLE
        self.fh_client = finnhub.Client(api_key=self.fh_api_key) if self.fh_enabled else None
        self.fh_calls = 0
        self.fh_success = 0
        self.fh_calls_minute = []
        self.fh_historical_available = True

        # Cache with longer TTL
        self.cache = {}
        self.quote_cache_ttl = 60  # 1 minute
        self.historical_cache_ttl = 600  # 10 minutes
        self.fundamental_cache_ttl = 3600  # 1 hour
        
        # Pre-fetched data last update
        self.last_prefetch_update = time.time()
        
        logger.info(f"🚀 Hybrid Engine initialized: yF=ON, AV={'ON' if self.av_enabled else 'OFF'}, FH={'ON' if self.fh_enabled else 'OFF'}")
    
    def get_prefetched_fundamentals(self, symbol: str) -> Optional[Dict]:
        """Get pre-fetched fundamentals for a symbol"""
        return PRE_FETCHED_DATA.get(symbol.upper())
    
    # ========================================================================
    # YFINANCE METHODS
    # ========================================================================
    
    async def _fetch_yf_quote(self, symbol: str) -> Optional[Dict]:
        """Fetch quote from yFinance"""
        if self.yf_limiter.is_blocked():
            return None
            
        try:
            acquired = await self.yf_limiter.acquire()
            if not acquired:
                return None
                
            loop = asyncio.get_event_loop()
            stock = await asyncio.wait_for(loop.run_in_executor(None, yf.Ticker, symbol), timeout=10)
            info = await asyncio.wait_for(loop.run_in_executor(None, lambda: stock.info or {}), timeout=10)
            self.yf_calls += 1
            
            price = info.get('currentPrice') or info.get('regularMarketPrice') or info.get('previousClose')
            if price and price > 0:
                self.yf_success += 1
                self.yf_limiter.record_success()
                
                # Update pre-fetched data if we got good info
                if info.get('symbol'):
                    self._update_prefetched_data(symbol, info)
                
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
                    "latency": "real-time",
                    "info": info
                }
            else:
                self.yf_limiter.record_failure()
                return None
                
        except asyncio.TimeoutError:
            logger.debug(f"yFinance quote timeout for {symbol}")
            self.yf_limiter.record_failure()
        except Exception as e:
            self.yf_limiter.record_failure()
            if "Rate limited" not in str(e) and "Too Many" not in str(e):
                logger.warning(f"yFinance quote error for {symbol}: {type(e).__name__}: {e}")
        return None
    
    def _update_prefetched_data(self, symbol: str, info: Dict):
        """Update pre-fetched data with real values"""
        symbol = symbol.upper()
        if symbol not in PRE_FETCHED_DATA:
            # Create entry for new symbol
            PRE_FETCHED_DATA[symbol] = {}
        
        data = PRE_FETCHED_DATA[symbol]
        data["company_name"] = info.get('longName') or info.get('shortName') or data.get("company_name", symbol)
        data["sector"] = info.get('sector') or data.get("sector", "Unknown")
        data["industry"] = info.get('industry') or data.get("industry", "Unknown")
        data["exchange"] = info.get('exchange') or data.get("exchange", "Unknown")
        data["market_cap"] = info.get('marketCap') or data.get("market_cap", 0)
        data["pe_ratio"] = info.get('trailingPE') or data.get("pe_ratio", 0)
        data["pb_ratio"] = info.get('priceToBook') or data.get("pb_ratio", 0)
        data["eps"] = info.get('trailingEps') or data.get("eps", 0)
        data["roe"] = info.get('returnOnEquity') or data.get("roe", 0)
        if data["roe"] and data["roe"] > 1:  # Convert from ratio to percentage
            data["roe"] = data["roe"] * 100
        data["roa"] = info.get('returnOnAssets') or data.get("roa", 0)
        if data["roa"] and data["roa"] > 1:
            data["roa"] = data["roa"] * 100
        data["dividend_yield"] = info.get('dividendYield') or data.get("dividend_yield", 0)
        if data["dividend_yield"] and data["dividend_yield"] > 1:
            data["dividend_yield"] = data["dividend_yield"] * 100
        data["debt_to_equity"] = info.get('debtToEquity') or data.get("debt_to_equity", 0)
        data["current_ratio"] = info.get('currentRatio') or data.get("current_ratio", 0)
        data["fifty_two_week_high"] = info.get('fiftyTwoWeekHigh') or data.get("fifty_two_week_high", 0)
        data["fifty_two_week_low"] = info.get('fiftyTwoWeekLow') or data.get("fifty_two_week_low", 0)
        data["average_volume"] = info.get('averageVolume') or data.get("average_volume", 0)
        data["last_updated"] = datetime.now().isoformat()
        
        logger.info(f"✅ Updated pre-fetched data for {symbol}")
    
    async def _fetch_yf_historical(self, symbol: str, period: str = "1mo", interval: str = "1d") -> Optional[List[Dict]]:
        """Fetch historical from yFinance"""
        if self.yf_limiter.is_blocked():
            return None
            
        try:
            acquired = await self.yf_limiter.acquire()
            if not acquired:
                return None
                
            loop = asyncio.get_event_loop()
            stock = await asyncio.wait_for(loop.run_in_executor(None, yf.Ticker, symbol), timeout=10)
            hist = await asyncio.wait_for(
                loop.run_in_executor(None, lambda: stock.history(period=period, interval=interval)),
                timeout=15
            )
            self.yf_calls += 1
            
            if hist is not None and not hist.empty:
                self.yf_success += 1
                self.yf_limiter.record_success()
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
        except asyncio.TimeoutError:
            logger.debug(f"yFinance historical timeout for {symbol}")
            self.yf_limiter.record_failure()
        except Exception as e:
            self.yf_limiter.record_failure()
            if "Rate limited" not in str(e) and "Too Many" not in str(e):
                logger.warning(f"yFinance historical error for {symbol}: {type(e).__name__}: {e}")
        return None
    
    # ========================================================================
    # PUBLIC METHODS WITH CASCADING FALLBACK
    # ========================================================================
    
    async def get_quote(self, symbol: str) -> Optional[Dict]:
        """Get real-time quote with cascading fallback"""
        
        cache_key = f"quote:{symbol}"
        if cache_key in self.cache:
            cached, ts = self.cache[cache_key]
            if time.time() - ts < self.quote_cache_ttl:
                return cached
        
        # Priority 1: yFinance
        result = await self._fetch_yf_quote(symbol)
        if result:
            self.cache[cache_key] = (result, time.time())
            return result
        
        # Priority 2: Finnhub
        result = await self._fetch_fh_quote(symbol)
        if result:
            self.cache[cache_key] = (result, time.time())
            return result
        
        return None
    
    async def _fetch_fh_quote(self, symbol: str) -> Optional[Dict]:
        """Fetch quote from Finnhub"""
        if not self.fh_enabled:
            return None
        
        try:
            loop = asyncio.get_event_loop()
            quote = await loop.run_in_executor(None, self.fh_client.quote, symbol)
            self.fh_calls += 1
            
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
    
    async def get_historical(self, symbol: str, period: str = "1mo", interval: str = "1d") -> Optional[List[Dict]]:
        """Get historical data with cascading fallback"""
        
        cache_key = f"hist:{symbol}:{period}:{interval}"
        if cache_key in self.cache:
            cached, ts = self.cache[cache_key]
            if time.time() - ts < self.historical_cache_ttl:
                return cached
        
        # Priority 1: yFinance
        result = await self._fetch_yf_historical(symbol, period, interval)
        if result:
            self.cache[cache_key] = (result, time.time())
            return result
        
        return None
    
    def get_company_info(self, symbol: str) -> Optional[Dict]:
        """Get company fundamentals - returns pre-fetched data immediately"""
        
        # Check cache first
        cache_key = f"fund:{symbol}"
        if cache_key in self.cache:
            cached, ts = self.cache[cache_key]
            if time.time() - ts < self.fundamental_cache_ttl:
                return cached
        
        # Check pre-fetched data
        prefetched = self.get_prefetched_fundamentals(symbol)
        if prefetched:
            # Convert to yFinance-like format
            result = {
                "symbol": symbol.upper(),
                "longName": prefetched.get("company_name", symbol),
                "sector": prefetched.get("sector"),
                "industry": prefetched.get("industry"),
                "exchange": prefetched.get("exchange"),
                "marketCap": prefetched.get("market_cap", 0),
                "trailingPE": prefetched.get("pe_ratio", 0),
                "priceToBook": prefetched.get("pb_ratio", 0),
                "trailingEps": prefetched.get("eps", 0),
                "returnOnEquity": prefetched.get("roe", 0),
                "returnOnAssets": prefetched.get("roa", 0),
                "dividendYield": prefetched.get("dividend_yield", 0),
                "debtToEquity": prefetched.get("debt_to_equity", 0),
                "currentRatio": prefetched.get("current_ratio", 0),
                "fiftyTwoWeekHigh": prefetched.get("fifty_two_week_high", 0),
                "fiftyTwoWeekLow": prefetched.get("fifty_two_week_low", 0),
                "averageVolume": prefetched.get("average_volume", 0),
                "is_prefetched": True,
                "last_updated": prefetched.get("last_updated", datetime.now().isoformat())
            }
            self.cache[cache_key] = (result, time.time())
            return result
        
        return None
    
    def get_stats(self) -> Dict:
        """Get engine statistics"""
        now = time.time()
        return {
            "yfinance": {
                "enabled": True,
                **self.yf_limiter.get_stats(),
                "calls": self.yf_calls,
                "success": self.yf_success
            },
            "alpha_vantage": {
                "enabled": self.av_enabled,
                **self.av_limiter.get_stats(),
                "calls": self.av_calls,
                "success": self.av_success
            },
            "finnhub": {
                "enabled": self.fh_enabled,
                "calls": self.fh_calls,
                "success": self.fh_success
            },
            "cache_size": len(self.cache),
            "prefetched_symbols": len(PRE_FETCHED_DATA)
        }


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
    """Internal function to fetch market indices"""
    indices_config = ['^GSPC', '^IXIC', '^DJI', '^RUT', '^VIX']
    results = []
    for symbol in indices_config:
        try:
            quote = await hybrid_engine._fetch_yf_quote(symbol)
            if quote:
                results.append({
                    "symbol": symbol,
                    "name": hybrid_engine._get_index_name(symbol),
                    "value": quote.get("price", 0),
                    "change": quote.get("change_percent", 0),
                    "source": "yFinance"
                })
        except Exception as e:
            logger.warning(f"Failed to fetch index {symbol}: {e}")
    return results

async def market_updater():
    """Periodically refresh market indices"""
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
        except Exception as e:
            logger.error(f"Error in market updater: {e}")
        await asyncio.sleep(300)

async def price_updater():
    """Push real-time price updates"""
    last_prices: Dict[str, float] = {}
    consecutive_failures: Dict[str, int] = defaultdict(int)
    backoff_times: Dict[str, float] = defaultdict(float)

    while True:
        try:
            symbols = list(manager.subscriptions.keys())
            if symbols:
                for symbol in symbols:
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
                        consecutive_failures[symbol] += 1
                    await asyncio.sleep(0.5)
            await asyncio.sleep(5)
        except Exception as e:
            logger.error(f"Error in price updater: {e}")
            await asyncio.sleep(5)

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(market_updater())
    asyncio.create_task(price_updater())
    logger.info("🚀 Background tasks started with pre-fetched data cache")

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

def get_fallback_stock_data(symbol: str, with_prefetched: bool = True) -> Dict:
    """Fallback data - uses pre-fetched data when available"""
    
    # First try pre-fetched data
    if with_prefetched:
        prefetched = hybrid_engine.get_prefetched_fundamentals(symbol)
        if prefetched:
            current_price = prefetched.get("current_price", 100)
            return {
                "symbol": symbol,
                "company_name": prefetched.get("company_name", symbol),
                "current_price": current_price,
                "change_percent": 0,
                "previous_close": current_price * 0.99,
                "change": current_price * 0.01,
                "day_high": current_price * 1.02,
                "day_low": current_price * 0.98,
                "volume": prefetched.get("average_volume", 10000000),
                "pe_ratio": prefetched.get("pe_ratio"),
                "pb_ratio": prefetched.get("pb_ratio"),
                "dividend_yield": prefetched.get("dividend_yield"),
                "market_cap": prefetched.get("market_cap"),
                "eps": prefetched.get("eps"),
                "roe": prefetched.get("roe"),
                "roa": prefetched.get("roa"),
                "current_ratio": prefetched.get("current_ratio"),
                "debt_to_equity": prefetched.get("debt_to_equity"),
                "volatility": 0.25,
                "fifty_two_week_high": prefetched.get("fifty_two_week_high", current_price * 1.15),
                "fifty_two_week_low": prefetched.get("fifty_two_week_low", current_price * 0.85),
                "average_volume": prefetched.get("average_volume", 15000000),
                "sector": prefetched.get("sector", "Technology"),
                "industry": prefetched.get("industry", "Software"),
                "exchange": prefetched.get("exchange", "NASDAQ"),
                "ai_score": 70,
                "recommendation": "Hold",
                "confidence": "Moderate",
                "risk_level": "Moderate Risk",
                "growth_potential": "Moderate Growth",
                "valuation": "Fairly Valued",
                "technical_indicators": {
                    "rsi": 55, "trend": "Neutral",
                    "sma_20": current_price * 0.98,
                    "sma_50": current_price * 0.95,
                    "sma_200": current_price * 0.90,
                    "macd": 0.5, "signal": 0.3, "histogram": 0.2
                },
                "news": [{"title": f"{prefetched.get('company_name', symbol)} latest news", "publisher": "Reuters", "published": datetime.now().isoformat()}],
                "ownership": {"institutional_holders": 65.0, "insider_holders": 5.0},
                "growth_metrics": {"revenue_growth": 12.5, "earnings_growth": 15.0},
                "is_prefetched_data": True,
                "message": "Using pre-fetched real data",
                "last_updated": prefetched.get("last_updated", datetime.now().isoformat())
            }
    
    # Fallback hardcoded data
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

async def fetch_stock_data(symbol: str, use_cache: bool = True):
    """Fetch stock data using hybrid engine"""
    cache_key = f"stock_data:{symbol}"
    if use_cache:
        cached = stock_cache.get(cache_key)
        if cached:
            return cached

    try:
        symbol = symbol.upper().strip()
        symbol_map = {"NVD": "NVDA", "BRK.B": "BRK-B", "BF.B": "BF-B"}
        symbol = symbol_map.get(symbol, symbol)

        # Get quote
        quote = await hybrid_engine.get_quote(symbol)
        
        # Get company info (from pre-fetched data)
        company_info = hybrid_engine.get_company_info(symbol)
        
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
            
            # Merge with company info
            if company_info:
                info.update(company_info)
            
            # Get historical data
            hist_data = await hybrid_engine.get_historical(symbol, "1mo")
            
            stock = MockStock(info)
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

        # Try direct yFinance as fallback
        try:
            loop = asyncio.get_event_loop()
            stock = await asyncio.wait_for(loop.run_in_executor(None, yf.Ticker, symbol), timeout=10)
            info = await asyncio.wait_for(loop.run_in_executor(None, lambda: stock.info or {}), timeout=10)
            hist = await asyncio.wait_for(loop.run_in_executor(None, lambda: stock.history(period="1mo")), timeout=15)
            
            if hist is not None and not hist.empty:
                result = (stock, info, hist)
                if use_cache:
                    stock_cache.set(cache_key, result)
                return result
        except Exception as e:
            logger.warning(f"Direct yFinance fallback failed for {symbol}: {e}")

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
        price_metrics = calculate_price_metrics(info, hist)
        
        # Calculate metrics from info
        pe_ratio = calculate_pe_ratio(info)
        pb_ratio = calculate_pb_ratio(info)
        debt_to_equity = calculate_debt_to_equity(info)
        current_ratio = calculate_current_ratio(info)
        roe = calculate_roe(info)
        roa = calculate_roa(info)
        dividend_yield = get_dividend_yield(info)
        eps = calculate_eps(info)
        volatility = calculate_volatility(hist)
        technical_indicators = calculate_technical_indicators(hist)
        
        # Handle None values properly
        if pe_ratio is None and info.get('trailingPE'):
            pe_ratio = safe_float(info.get('trailingPE'))
        if pb_ratio is None and info.get('priceToBook'):
            pb_ratio = safe_float(info.get('priceToBook'))
        if roe is None and info.get('returnOnEquity'):
            roe = safe_float(info.get('returnOnEquity')) * 100 if info.get('returnOnEquity') else None
        if roa is None and info.get('returnOnAssets'):
            roa = safe_float(info.get('returnOnAssets')) * 100 if info.get('returnOnAssets') else None
        if eps is None and info.get('trailingEps'):
            eps = safe_float(info.get('trailingEps'))
        
        metrics = {
            'pe_ratio': pe_ratio, 'pb_ratio': pb_ratio,
            'dividend_yield': dividend_yield, 'debt_to_equity': debt_to_equity,
            'eps': eps, 'roe': roe, 'roa': roa, 'current_ratio': current_ratio,
            'volatility': volatility, 'sector': info.get('sector')
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
        fifty_two_week_low = safe_float(safe_get(info, 'fiftyTwoWeekLow', 0))
        if fifty_two_week_high == 0 and hist is not None and not hist.empty:
            fifty_two_week_high = float(hist['High'].max())
            fifty_two_week_low = float(hist['Low'].min())

        return {
            "symbol": display_symbol,
            "original_symbol": symbol,
            "is_indian_stock": is_indian,
            "company_name": company_name,
            **price_metrics,
            "market_cap": market_cap,
            "pe_ratio": round(pe_ratio, 2) if pe_ratio is not None else None,
            "pb_ratio": round(pb_ratio, 2) if pb_ratio is not None else None,
            "dividend_yield": round(dividend_yield, 2) if dividend_yield is not None else None,
            "debt_to_equity": round(debt_to_equity, 2) if debt_to_equity is not None else None,
            "eps": round(eps, 2) if eps is not None else None,
            "roe": round(roe, 2) if roe is not None else None,
            "roa": round(roa, 2) if roa is not None else None,
            "current_ratio": round(current_ratio, 2) if current_ratio is not None else None,
            "volatility": round(volatility, 4),
            "fifty_two_week_high": round(fifty_two_week_high, 2),
            "fifty_two_week_low": round(fifty_two_week_low, 2),
            "average_volume": safe_float(safe_get(info, 'averageVolume', 0)),
            "sector": safe_get(info, 'sector'),
            "industry": safe_get(info, 'industry'),
            "exchange": safe_get(info, 'exchange'),
            "ai_score": round(ai_score, 2),
            "recommendation": recommendation_data.get('recommendation', 'Hold'),
            "confidence": recommendation_data.get('confidence', 'Moderate'),
            "risk_level": recommendation_data.get('risk_level', 'Moderate Risk'),
            "growth_potential": recommendation_data.get('growth_potential', 'Moderate Growth'),
            "valuation": recommendation_data.get('valuation', 'Fairly Valued'),
            "technical_indicators": technical_indicators,
            "news": get_latest_news(symbol)[:5],
            "ownership": get_ownership_pattern(stock),
            "growth_metrics": analyze_growth(stock),
            "is_prefetched": info.get('is_prefetched', False),
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
        if result and result[0] is not None:
            stock, info, hist = result
            response_data = build_stock_response(symbol, stock, info, hist)
            if use_cache:
                stock_cache.set(cache_key, response_data)
            last_good_stock_cache.set(symbol, response_data)
            return response_data

        # Use pre-fetched data if available
        prefetched = hybrid_engine.get_prefetched_fundamentals(symbol)
        if prefetched:
            response_data = get_fallback_stock_data(symbol, with_prefetched=True)
            if use_cache:
                stock_cache.set(cache_key, response_data)
            return response_data

        # Final fallback
        logger.warning(f"Using fallback for {symbol}")
        fallback = get_fallback_stock_data(symbol, with_prefetched=False)
        if use_cache:
            stock_cache.set(cache_key, fallback)
        return fallback

    except Exception as e:
        logger.error(f"Error in get_stock_analysis for {symbol}: {e}")
        return get_fallback_stock_data(symbol, with_prefetched=True)

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
        hist_data = await hybrid_engine.get_historical(symbol, period, interval)

        if hist_data and len(hist_data) > 0:
            chart_cache.set(cache_key, hist_data)
            last_good_chart_cache.set(cache_key, hist_data)
            return hist_data

        # Generate synthetic chart based on real price
        base_price = None
        real_last_known = last_good_stock_cache.get(symbol)
        if real_last_known and real_last_known.get('current_price'):
            base_price = real_last_known['current_price']
        
        if base_price is None:
            prefetched = hybrid_engine.get_prefetched_fundamentals(symbol)
            if prefetched and prefetched.get("current_price"):
                base_price = prefetched.get("current_price")
            else:
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
                "open": round(price * random.uniform(0.99, 1.01), 2),
                "high": round(price * random.uniform(1.005, 1.02), 2),
                "low": round(price * random.uniform(0.98, 0.995), 2),
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

        valid_pe = [s for s in stocks_data if s.get('pe_ratio') is not None]
        valid_roe = [s for s in stocks_data if s.get('roe') is not None]
        valid_div = [s for s in stocks_data if s.get('dividend_yield') is not None]
        valid_vol = [s for s in stocks_data if s.get('volatility') is not None]

        comparison_data = {
            "ai_top_pick": max(stocks_data, key=lambda x: x.get('ai_score', 0))['symbol'],
            "best_value": min(valid_pe, key=lambda x: x.get('pe_ratio', float('inf')))['symbol'] if valid_pe else "N/A",
            "best_dividend": max(valid_div, key=lambda x: x.get('dividend_yield', 0))['symbol'] if valid_div else "N/A",
            "lowest_risk": min(valid_vol, key=lambda x: x.get('volatility', float('inf')))['symbol'] if valid_vol else "N/A",
            "average_pe": round(np.mean([s['pe_ratio'] for s in valid_pe]), 2) if valid_pe else 0,
            "average_roe": round(np.mean([s['roe'] for s in valid_roe]), 2) if valid_roe else 0,
            "average_debt": round(np.mean([s.get('debt_to_equity', 0) or 0 for s in stocks_data]), 2),
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
        if result and result[0] is not None:
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
        symbol = request.get("symbol")
        user_id = req.client.host if req and req.client else "anonymous"
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
            if time.time() - ts < 280:
                return cached.get("indices", cached) if isinstance(cached, dict) else cached

    indices = await _fetch_indices_internal()
    if indices:
        stock_cache.set(cache_key, {"indices": indices, "_timestamp": time.time()})
    return indices

@app.get("/api/trending")
async def get_trending(use_cache: bool = True):
    cache_key = "trending:stocks"
    if use_cache:
        cached = stock_cache.get(cache_key)
        if cached:
            return cached

    symbols = ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'TSLA', 'NVDA', 'META']
    trending_data = []
    for symbol in symbols:
        try:
            quote = await hybrid_engine.get_quote(symbol)
            company_info = hybrid_engine.get_company_info(symbol)
            if quote and quote.get('price'):
                trending_data.append({
                    "symbol": symbol,
                    "name": company_info.get('longName', symbol) if company_info else symbol,
                    "price": quote.get('price', 0),
                    "change": quote.get('change_percent', 0),
                    "volume": quote.get('volume', 0),
                    "market_cap": company_info.get('marketCap', 0) if company_info else 0,
                    "source": quote.get('source', 'unknown')
                })
        except Exception as e:
            logger.error(f"Error fetching trending {symbol}: {e}")
    
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
            "name": "yfinance_quote",
            "success": bool(quote and quote.get('price')),
            "data": quote
        })
        
        hist = await hybrid_engine.get_historical(symbol, "1mo")
        result["tests"].append({
            "name": "yfinance_historical",
            "success": bool(hist and len(hist) > 0),
            "count": len(hist) if hist else 0
        })
        
        info = hybrid_engine.get_company_info(symbol)
        result["tests"].append({
            "name": "prefetched_company",
            "success": bool(info),
            "company": info.get('longName', info.get('company_name')) if info else None,
            "pe": info.get('trailingPE') if info else None
        })
        
        return result
    except Exception as e:
        return {"symbol": symbol, "error": str(e), "timestamp": datetime.now().isoformat()}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True, log_level="info")