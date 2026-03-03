# backend/main.py
from fastapi import FastAPI, HTTPException, Request, status, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, validator, Field
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
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Import financials helpers
from financials import (
    calculate_pe_ratio, calculate_pb_ratio, calculate_debt_to_equity,
    calculate_current_ratio, calculate_roe, calculate_roa,
    get_dividend_yield, calculate_eps, analyze_growth,
    calculate_volatility, get_ownership_pattern,
    calculate_technical_indicators, get_latest_news,
    calculate_ai_score, generate_recommendation,
    is_indian_stock, normalize_indian_symbol
)

# Import AI service
from ai_service import ai_service

# ============= WEBSOCKET MANAGER =============
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self.subscriptions: Dict[str, List[WebSocket]] = {}

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)
        # Remove from subscriptions
        for symbol in list(self.subscriptions.keys()):
            if websocket in self.subscriptions[symbol]:
                self.subscriptions[symbol].remove(websocket)

    async def subscribe(self, websocket: WebSocket, symbol: str):
        if symbol not in self.subscriptions:
            self.subscriptions[symbol] = []
        self.subscriptions[symbol].append(websocket)

    async def broadcast_to_symbol(self, symbol: str, message: dict):
        if symbol in self.subscriptions:
            for connection in self.subscriptions[symbol]:
                try:
                    await connection.send_json(message)
                except:
                    pass

    async def broadcast_all(self, message: dict):
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except:
                pass

manager = ConnectionManager()

# ============= CONFIGURATION =============
class Config:
    API_TITLE = "Stock Advisor API"
    API_VERSION = "2.1.0"
    CACHE_TTL = int(os.getenv("CACHE_TTL", 60))  # Reduced to 60 seconds for real-time
    MAX_CACHE_SIZE = 1000
    RATE_LIMIT_REQUESTS = int(os.getenv("RATE_LIMIT_REQUESTS", 100))
    RATE_LIMIT_WINDOW = int(os.getenv("RATE_LIMIT_WINDOW", 60))
    MAX_COMPARISON_STOCKS = int(os.getenv("MAX_COMPARISON_STOCKS", 5))
    MIN_COMPARISON_STOCKS = int(os.getenv("MIN_COMPARISON_STOCKS", 2))
    ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "http://localhost:5173,http://localhost:3000").split(",")
    REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
    REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
    REDIS_DB = int(os.getenv("REDIS_DB", 0))

config = Config()

# ============= CACHING =============
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
        """Delete all keys containing pattern"""
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

# Initialize caches
stock_cache = LRUCache(max_size=config.MAX_CACHE_SIZE, ttl=config.CACHE_TTL)
chart_cache = LRUCache(max_size=config.MAX_CACHE_SIZE, ttl=config.CACHE_TTL)

# ============= FASTAPI APP =============
app = FastAPI(
    title=config.API_TITLE,
    version=config.API_VERSION,
    description="Production-ready stock analysis API with AI features",
    docs_url="/api/docs",
    redoc_url="/api/redoc"
)

# CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============= VALIDATION MODELS =============
class StockRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=10)

    @validator('symbol')
    def validate_symbol(cls, v):
        v = v.upper().strip()
        if not v:
            raise ValueError('Symbol cannot be empty')
        if not re.match(r'^[A-Z]{1,5}(\.[A-Z]{2})?$', v):
            raise ValueError('Invalid symbol format. Use 1-5 uppercase letters, optionally with .NS or .BO suffix.')
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
            if not re.match(r'^[A-Z]{1,5}(\.[A-Z]{2})?$', symbol):
                raise ValueError(f'Invalid symbol: {symbol}')
            cleaned.append(symbol)
        
        if len(cleaned) != len(set(cleaned)):
            raise ValueError('Duplicate symbols detected')
        
        return cleaned

# ============= WEBSOCKET ENDPOINT =============
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
async def market_updater():
    """Update market indices every minute"""
    while True:
        try:
            # Invalidate market cache
            stock_cache.delete_pattern("market:indices")
            # Fetch and broadcast updates
            indices = await get_market_indices(use_cache=False)
            await manager.broadcast_all({
                "type": "market_update",
                "data": indices,
                "timestamp": datetime.now().isoformat()
            })
            logger.info("Market indices updated via WebSocket")
        except Exception as e:
            logger.error(f"Error in market updater: {e}")
        await asyncio.sleep(60)  # Update every minute

async def price_updater():
    """Update stock prices every 5 seconds for subscribed symbols"""
    while True:
        try:
            # Get all subscribed symbols
            symbols = list(manager.subscriptions.keys())
            if symbols:
                for symbol in symbols:
                    try:
                        # Fetch latest price
                        stock = yf.Ticker(symbol)
                        hist = stock.history(period="1d", interval="1m")
                        if not hist.empty:
                            current_price = float(hist['Close'].iloc[-1])
                            prev_close = float(hist['Close'].iloc[-2]) if len(hist) > 1 else current_price
                            change = ((current_price - prev_close) / prev_close) * 100
                            
                            # Broadcast to subscribers
                            await manager.broadcast_to_symbol(symbol, {
                                "type": "price_update",
                                "symbol": symbol,
                                "price": round(current_price, 2),
                                "change": round(change, 2),
                                "timestamp": datetime.now().isoformat()
                            })
                    except Exception as e:
                        logger.error(f"Error updating price for {symbol}: {e}")
        except Exception as e:
            logger.error(f"Error in price updater: {e}")
        await asyncio.sleep(5)  # Update every 5 seconds

@app.on_event("startup")
async def startup_event():
    """Start background tasks on startup"""
    asyncio.create_task(market_updater())
    asyncio.create_task(price_updater())
    logger.info("Background tasks started")

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
    """Invalidate all cache entries for a symbol"""
    stock_cache.delete_pattern(symbol)
    chart_cache.delete_pattern(symbol)
    logger.info(f"Invalidated cache for {symbol}")

async def fetch_stock_data(symbol: str, use_cache: bool = True) -> tuple:
    """Asynchronously fetch stock data with better error handling"""
    cache_key = f"stock_data:{symbol}"
    
    if use_cache:
        cached_data = stock_cache.get(cache_key)
        if cached_data:
            logger.info(f"Cache hit for {symbol}")
            return cached_data
    
    try:
        loop = asyncio.get_event_loop()
        
        logger.info(f"Fetching data for {symbol}")
        
        # Create ticker
        try:
            stock = await loop.run_in_executor(None, yf.Ticker, symbol)
        except Exception as e:
            logger.error(f"Error creating ticker for {symbol}: {e}")
            raise HTTPException(
                status_code=404,
                detail=f"Could not create ticker for {symbol}"
            )
        
        # Fetch info with timeout
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
        
        # Check if we got valid info
        if not info or len(info) < 5:
            logger.warning(f"Limited info received for {symbol}: {len(info) if info else 0} keys")
            
            # Try alternative symbol formats
            if not symbol.endswith('.NS') and not symbol.endswith('.BO'):
                # Try with .NS suffix for Indian stocks
                alt_symbol = symbol + '.NS'
                try:
                    logger.info(f"Trying alternative symbol: {alt_symbol}")
                    alt_stock = await loop.run_in_executor(None, yf.Ticker, alt_symbol)
                    alt_info = await asyncio.wait_for(
                        loop.run_in_executor(None, lambda: alt_stock.info or {}),
                        timeout=10.0
                    )
                    if alt_info and len(alt_info) > 5:
                        logger.info(f"Success with {alt_symbol} instead")
                        stock = alt_stock
                        info = alt_info
                        symbol = alt_symbol
                except Exception as e:
                    logger.debug(f"Alternative symbol failed: {e}")
        
        # Fetch history
        try:
            hist = await asyncio.wait_for(
                loop.run_in_executor(None, lambda: stock.history(period="1y")),
                timeout=10.0
            )
        except asyncio.TimeoutError:
            logger.error(f"Timeout fetching history for {symbol}")
            raise ValueError(f"Timeout fetching historical data for {symbol}")
        except Exception as e:
            logger.error(f"Error fetching history for {symbol}: {e}")
            raise ValueError(f"No historical data available for {symbol}")
        
        if hist is None or hist.empty:
            logger.error(f"Empty history for {symbol}")
            raise ValueError(f"No historical data available for {symbol}")
        
        result = (stock, info, hist)
        
        if use_cache:
            stock_cache.set(cache_key, result)
        
        logger.info(f"Successfully fetched data for {symbol}")
        return result
        
    except HTTPException:
        raise
    except ValueError as e:
        logger.error(f"Value error for {symbol}: {str(e)}")
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error fetching data for {symbol}: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error fetching data for {symbol}: {str(e)}"
        )

def calculate_price_metrics(info: Dict, hist) -> Dict:
    """Calculate current price and changes"""
    try:
        current_price = (
            info.get('currentPrice') or 
            info.get('regularMarketPrice') or 
            info.get('previousClose') or
            (hist['Close'].iloc[-1] if len(hist) > 0 else 0.0)
        )
        
        previous_close = (
            info.get('previousClose') or
            (hist['Close'].iloc[-2] if len(hist) > 1 else current_price)
        )
        
        current_price = safe_float(current_price)
        previous_close = safe_float(previous_close)
        
        change = current_price - previous_close
        change_percent = (
            ((current_price - previous_close) / previous_close) * 100
            if previous_close and previous_close != 0 else 0.0
        )
        
        day_high = info.get('dayHigh') or (hist['High'].iloc[-1] if len(hist) > 0 else current_price)
        day_low = info.get('dayLow') or (hist['Low'].iloc[-1] if len(hist) > 0 else current_price)
        
        return {
            "current_price": round(current_price, 2),
            "previous_close": round(previous_close, 2),
            "change": round(change, 2),
            "change_percent": round(change_percent, 2),
            "day_high": round(safe_float(day_high), 2),
            "day_low": round(safe_float(day_low), 2),
            "volume": safe_float(info.get('volume', 0))
        }
    except Exception as e:
        logger.error(f"Error calculating price metrics: {str(e)}")
        return {
            "current_price": 0.0,
            "previous_close": 0.0,
            "change": 0.0,
            "change_percent": 0.0,
            "day_high": 0.0,
            "day_low": 0.0,
            "volume": 0
        }

def build_stock_response(symbol: str, stock, info: Dict, hist) -> Dict:
    """Build comprehensive stock response"""
    try:
        price_metrics = calculate_price_metrics(info, hist)
        
        # Calculate all financial metrics
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
        growth_metrics = analyze_growth(stock)
        ownership = get_ownership_pattern(stock)
        news = get_latest_news(symbol)
        
        metrics = {
            'pe_ratio': pe_ratio,
            'pb_ratio': pb_ratio,
            'dividend_yield': dividend_yield,
            'debt_to_equity': debt_to_equity,
            'eps': eps,
            'roe': roe,
            'roa': roa,
            'current_ratio': current_ratio,
            'volatility': volatility,
            'growth_metrics': growth_metrics,
            'technical_indicators': technical_indicators
        }
        
        ai_score = calculate_ai_score(metrics)
        recommendation_data = generate_recommendation(ai_score, metrics)
        
        # Determine if Indian stock
        is_indian = is_indian_stock(symbol)
        display_symbol = normalize_indian_symbol(symbol) if is_indian else symbol
        
        # Get company name safely
        company_name = safe_get(info, 'longName', display_symbol)
        if not company_name or company_name == display_symbol:
            company_name = safe_get(info, 'shortName', display_symbol)
        
        return {
            "symbol": display_symbol,
            "original_symbol": symbol,
            "is_indian_stock": is_indian,
            "company_name": company_name,
            **price_metrics,
            "market_cap": safe_float(safe_get(info, 'marketCap', 0)),
            "pe_ratio": round(pe_ratio, 2) if pe_ratio is not None else None,
            "pb_ratio": round(pb_ratio, 2) if pb_ratio is not None else None,
            "dividend_yield": round(dividend_yield, 2) if dividend_yield is not None else None,
            "debt_to_equity": round(debt_to_equity, 2) if debt_to_equity is not None else None,
            "eps": round(eps, 2) if eps is not None else None,
            "roe": round(roe, 2) if roe is not None else None,
            "roa": round(roa, 2) if roa is not None else None,
            "current_ratio": round(current_ratio, 2) if current_ratio is not None else None,
            "volatility": round(volatility, 4),
            "fifty_two_week_high": safe_float(safe_get(info, 'fiftyTwoWeekHigh', 0)),
            "fifty_two_week_low": safe_float(safe_get(info, 'fiftyTwoWeekLow', 0)),
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
            "news": news[:5],
            "ownership": ownership,
            "growth_metrics": growth_metrics,
            "last_updated": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Error building response for {symbol}: {str(e)}")
        raise

# ============= API ENDPOINTS =============
@app.get("/")
async def root():
    return {
        "service": config.API_TITLE,
        "version": config.API_VERSION,
        "status": "operational",
        "timestamp": datetime.now().isoformat(),
        "endpoints": {
            "health": "/health",
            "stock_analysis": "/api/stock/{symbol}",
            "chart_data": "/api/stock/{symbol}/chart",
            "compare": "/api/compare",
            "trending": "/api/trending",
            "market_indices": "/api/market-indices",
            "search": "/api/search/{query}",
            "ai_compare": "/api/ai/compare",
            "ai_thesis": "/api/ai/thesis/{symbol}",
            "ai_question": "/api/ai/question",
            "ai_sentiment": "/api/ai/sentiment",
            "cache_invalidate": "/api/cache/invalidate/{symbol}",
            "debug": "/api/debug/{symbol}",
            "docs": "/api/docs",
            "websocket": "/ws"
        }
    }

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "version": config.API_VERSION,
        "cache_stats": stock_cache.stats()
    }

@app.post("/api/cache/invalidate/{symbol}")
async def invalidate_cache(symbol: str):
    """Invalidate cache for a specific symbol"""
    try:
        symbol = symbol.upper().strip()
        invalidate_symbol_cache(symbol)
        return {
            "status": "success",
            "message": f"Cache invalidated for {symbol}",
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Error invalidating cache: {e}")
        return {
            "status": "error",
            "message": str(e)
        }

@app.get("/api/debug/{symbol}")
async def debug_stock(symbol: str):
    """Debug endpoint to check stock data fetching"""
    try:
        symbol = symbol.upper().strip()
        logger.info(f"Debug endpoint called for {symbol}")
        
        import yfinance as yf
        from yfinance.exceptions import YFinanceException
        
        result = {
            "symbol": symbol,
            "timestamp": datetime.now().isoformat(),
            "tests": []
        }
        
        # Test 1: Create ticker
        try:
            stock = yf.Ticker(symbol)
            result["tests"].append({
                "name": "create_ticker",
                "success": True,
                "message": f"Ticker created for {symbol}"
            })
        except Exception as e:
            result["tests"].append({
                "name": "create_ticker",
                "success": False,
                "error": str(e)
            })
            return result
        
        # Test 2: Get info
        try:
            info = stock.info
            info_keys = list(info.keys()) if info else []
            result["tests"].append({
                "name": "get_info",
                "success": bool(info and len(info) > 0),
                "info_keys_count": len(info_keys),
                "info_sample": info_keys[:10] if info_keys else [],
                "has_longName": "longName" in info if info else False,
                "has_regularMarketPrice": "regularMarketPrice" in info if info else False
            })
        except Exception as e:
            result["tests"].append({
                "name": "get_info",
                "success": False,
                "error": str(e)
            })
        
        # Test 3: Get history
        try:
            hist = stock.history(period="1mo")
            hist_empty = hist.empty if hist is not None else True
            result["tests"].append({
                "name": "get_history",
                "success": not hist_empty,
                "history_days": len(hist) if not hist_empty else 0,
                "history_columns": list(hist.columns) if not hist_empty else []
            })
        except Exception as e:
            result["tests"].append({
                "name": "get_history",
                "success": False,
                "error": str(e)
            })
        
        # Test 4: Try alternative symbol if needed
        if not symbol.endswith('.NS') and not symbol.endswith('.BO'):
            alt_symbol = symbol + '.NS'
            try:
                alt_stock = yf.Ticker(alt_symbol)
                alt_info = alt_stock.info
                if alt_info and len(alt_info) > 5:
                    result["tests"].append({
                        "name": "alternative_symbol",
                        "success": True,
                        "alternative": alt_symbol,
                        "message": f"Alternative symbol {alt_symbol} works"
                    })
            except:
                pass
        
        return result
        
    except Exception as e:
        logger.error(f"Debug endpoint error: {e}")
        return {
            "symbol": symbol,
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }

@app.get("/api/stock/{symbol}")
async def get_stock_analysis(symbol: str, use_cache: bool = True):
    """Get comprehensive stock analysis"""
    try:
        symbol = symbol.upper().strip()
        logger.info(f"Stock analysis requested for {symbol}")
        
        cache_key = f"stock:{symbol}"
        if use_cache:
            cached_data = stock_cache.get(cache_key)
            if cached_data:
                logger.info(f"Cache hit for {symbol}")
                return cached_data
        
        logger.info(f"Fetching fresh data for {symbol}")
        stock, info, hist = await fetch_stock_data(symbol)
        response_data = build_stock_response(symbol, stock, info, hist)
        
        if use_cache:
            stock_cache.set(cache_key, response_data)
        
        return response_data
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in get_stock_analysis for {symbol}: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error while analyzing {symbol}"
        )

@app.get("/api/stock/{symbol}/chart")
async def get_stock_chart(symbol: str, period: str = "1mo", use_cache: bool = True):
    """Get historical chart data"""
    try:
        symbol = symbol.upper().strip()
        
        valid_periods = ["1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y", "max"]
        if period not in valid_periods:
            period = "1mo"
        
        cache_key = f"chart:{symbol}:{period}"
        if use_cache:
            cached_data = chart_cache.get(cache_key)
            if cached_data:
                return cached_data
        
        loop = asyncio.get_event_loop()
        stock = await loop.run_in_executor(None, yf.Ticker, symbol)
        hist = await loop.run_in_executor(None, lambda: stock.history(period=period))
        
        if hist is None or hist.empty:
            raise HTTPException(
                status_code=404,
                detail=f"No chart data available for {symbol}"
            )
        
        chart_data = []
        for date, row in hist.iterrows():
            chart_data.append({
                "date": date.isoformat(),
                "price": round(float(row['Close']), 2),
                "open": round(float(row['Open']), 2),
                "high": round(float(row['High']), 2),
                "low": round(float(row['Low']), 2),
                "volume": int(row['Volume']) if 'Volume' in row else 0
            })
        
        if use_cache:
            chart_cache.set(cache_key, chart_data)
        
        return chart_data
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching chart for {symbol}: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error fetching chart data for {symbol}"
        )

@app.post("/api/compare")
async def compare_stocks(request: CompareRequest):
    """Compare multiple stocks"""
    try:
        symbols = request.symbols
        
        tasks = [fetch_stock_data(symbol) for symbol in symbols]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        stocks_data = []
        failed_symbols = []
        
        for i, result in enumerate(results):
            symbol = symbols[i]
            if isinstance(result, Exception):
                failed_symbols.append(f"{symbol}: {str(result)}")
                continue
            
            try:
                stock, info, hist = result
                stock_response = build_stock_response(symbol, stock, info, hist)
                stocks_data.append(stock_response)
            except Exception as e:
                failed_symbols.append(f"{symbol}: {str(e)}")
        
        if len(stocks_data) < config.MIN_COMPARISON_STOCKS:
            raise HTTPException(
                status_code=400,
                detail=f"Need at least {config.MIN_COMPARISON_STOCKS} valid stocks. Failed: {', '.join(failed_symbols)}"
            )
        
        valid_pe = [s for s in stocks_data if s.get('pe_ratio') is not None]
        valid_roe = [s for s in stocks_data if s.get('roe') is not None]
        valid_div = [s for s in stocks_data if s.get('dividend_yield') is not None]
        valid_volatility = [s for s in stocks_data if s.get('volatility') is not None]
        
        comparison_data = {
            "ai_top_pick": max(stocks_data, key=lambda x: x['ai_score'])['symbol'],
            "best_value": min(valid_pe, key=lambda x: x['pe_ratio'])['symbol'] if valid_pe else "N/A",
            "best_dividend": max(valid_div, key=lambda x: x['dividend_yield'])['symbol'] if valid_div else "N/A",
            "lowest_risk": min(valid_volatility, key=lambda x: x['volatility'])['symbol'] if valid_volatility else "N/A",
            "average_pe": round(np.mean([s['pe_ratio'] for s in valid_pe]), 2) if valid_pe else 0,
            "average_roe": round(np.mean([s['roe'] for s in valid_roe]), 2) if valid_roe else 0,
            "average_div": round(np.mean([s['dividend_yield'] for s in valid_div]), 2) if valid_div else 0,
            "average_volatility": round(np.mean([s['volatility'] for s in valid_volatility]), 2) if valid_volatility else 0,
            "average_debt": round(np.mean([s['debt_to_equity'] for s in stocks_data if s.get('debt_to_equity')]), 2),
            "successful_symbols": [s['symbol'] for s in stocks_data],
            "failed_symbols": failed_symbols
        }
        
        return {
            "stocks": stocks_data,
            "comparison": comparison_data
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error comparing stocks: {str(e)}")
        raise HTTPException(status_code=500, detail="Error comparing stocks")

@app.post("/api/ai/compare")
async def ai_compare_stocks(request: CompareRequest, req: Request = None):
    """AI-powered stock comparison with rate limiting"""
    try:
        symbols = request.symbols
        
        # Get user identifier for rate limiting (IP address)
        user_id = "anonymous"
        if req and req.client:
            user_id = req.client.host
        
        tasks = [fetch_stock_data(symbol) for symbol in symbols]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        stocks_data = []
        failed_symbols = []
        
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                failed_symbols.append(symbols[i])
                continue
            stock, info, hist = result
            stock_response = build_stock_response(symbols[i], stock, info, hist)
            stocks_data.append(stock_response)
        
        if len(stocks_data) < 2:
            return {
                "success": False,
                "error": "Need at least 2 valid stocks",
                "failed_symbols": failed_symbols
            }
        
        # Pass user_id for rate limiting
        ai_analysis = await ai_service.analyze_stock_comparison(stocks_data, user_id=user_id)
        
        # Add rate limit info to response
        rate_limit_stats = ai_service.get_rate_limit_stats()
        
        return {
            "success": True,
            "stocks": stocks_data,
            "ai_analysis": ai_analysis,
            "failed_symbols": failed_symbols,
            "rate_limit": rate_limit_stats,
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error in AI comparison: {e}")
        return {
            "success": False,
            "error": str(e)
        }

@app.get("/api/ai/thesis/{symbol}")
async def get_ai_thesis(symbol: str, req: Request = None):
    """Generate AI investment thesis for a stock"""
    try:
        symbol = symbol.upper().strip()
        user_id = req.client.host if req and req.client else "anonymous"
        
        stock, info, hist = await fetch_stock_data(symbol)
        stock_data = build_stock_response(symbol, stock, info, hist)
        
        news = get_latest_news(symbol)
        
        thesis = await ai_service.generate_investment_thesis(stock_data, news, user_id=user_id)
        
        return {
            "success": True,
            "symbol": symbol,
            "thesis": thesis,
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error generating thesis: {e}")
        return {
            "success": False,
            "error": str(e)
        }

@app.post("/api/ai/question")
async def ask_ai_question(request: dict, req: Request = None):
    """Ask any investment question to AI"""
    try:
        question = request.get("question")
        symbol = request.get("symbol")
        user_id = req.client.host if req and req.client else "anonymous"
        
        if not question:
            return {"success": False, "error": "Question is required"}
        
        stock_data = None
        if symbol:
            try:
                stock, info, hist = await fetch_stock_data(symbol)
                stock_data = build_stock_response(symbol, stock, info, hist)
            except:
                pass
        
        answer = await ai_service.answer_question(question, stock_data, user_id=user_id)
        
        return {
            "success": True,
            "question": question,
            "answer": answer,
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error answering question: {e}")
        return {
            "success": False,
            "error": str(e)
        }

@app.post("/api/ai/sentiment")
async def analyze_sentiment(request: dict, req: Request = None):
    """Analyze market sentiment for symbols"""
    try:
        symbols = request.get("symbols", [])
        user_id = req.client.host if req and req.client else "anonymous"
        
        if not symbols:
            return {"success": False, "error": "Symbols required"}
        
        news_data = {}
        for symbol in symbols:
            news = get_latest_news(symbol, max_news=3)
            news_data[symbol] = news
        
        sentiment = await ai_service.get_market_sentiment(symbols, news_data, user_id=user_id)
        
        return {
            "success": True,
            "sentiment": sentiment,
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error analyzing sentiment: {e}")
        return {
            "success": False,
            "error": str(e)
        }

@app.get("/api/market-indices")
async def get_market_indices(use_cache: bool = True):
    """Get major market indices"""
    cache_key = "market:indices"
    if use_cache:
        cached_data = stock_cache.get(cache_key)
        if cached_data:
            return cached_data
    
    indices = {
        '^GSPC': 'S&P 500',
        '^IXIC': 'NASDAQ',
        '^DJI': 'DOW JONES',
        '^RUT': 'RUSSELL 2000',
        '^VIX': 'VIX',
        'BTC-USD': 'Bitcoin',
        'GC=F': 'Gold',
        'CL=F': 'Crude Oil'
    }
    
    async def fetch_index(symbol, name):
        try:
            loop = asyncio.get_event_loop()
            stock = await loop.run_in_executor(None, yf.Ticker, symbol)
            hist = await loop.run_in_executor(None, lambda: stock.history(period="2d"))
            
            if hist is not None and len(hist) >= 2:
                current = float(hist['Close'].iloc[-1])
                previous = float(hist['Close'].iloc[-2])
                change_pct = ((current - previous) / previous) * 100
                return {
                    "name": name,
                    "value": round(current, 2),
                    "change": round(change_pct, 2)
                }
        except:
            pass
        return {"name": name, "value": 0.0, "change": 0.0}
    
    tasks = [fetch_index(symbol, name) for symbol, name in indices.items()]
    indices_data = await asyncio.gather(*tasks)
    
    if use_cache:
        stock_cache.set(cache_key, indices_data)
    
    return indices_data

@app.get("/api/trending")
async def get_trending(use_cache: bool = True):
    """Get trending stocks (including Indian stocks)"""
    cache_key = "trending:stocks"
    if use_cache:
        cached_data = stock_cache.get(cache_key)
        if cached_data:
            return cached_data
    
    symbols = [
        'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'TSLA', 'NVDA', 'META',
        'RELIANCE.NS', 'TCS.NS', 'HDFCBANK.NS', 'INFY.NS', 'ICICIBANK.NS',
        'ITC.NS', 'SBIN.NS', 'BHARTIARTL.NS', 'WIPRO.NS', 'TATAMOTORS.NS'
    ]
    
    async def fetch_trending(symbol):
        try:
            loop = asyncio.get_event_loop()
            stock = await loop.run_in_executor(None, yf.Ticker, symbol)
            info = await loop.run_in_executor(None, lambda: stock.info or {})
            hist = await loop.run_in_executor(None, lambda: stock.history(period="5d"))
            
            if hist is not None and len(hist) > 0:
                current = float(hist['Close'].iloc[-1])
                previous = float(hist['Close'].iloc[-2]) if len(hist) > 1 else current
                change_pct = ((current - previous) / previous) * 100
                
                display_symbol = normalize_indian_symbol(symbol)
                
                return {
                    "symbol": display_symbol,
                    "original_symbol": symbol,
                    "name": safe_get(info, 'longName', display_symbol),
                    "price": round(current, 2),
                    "change": round(change_pct, 2),
                    "volume": safe_float(safe_get(info, 'volume', 0)),
                    "market_cap": safe_float(safe_get(info, 'marketCap', 0)),
                    "is_indian": is_indian_stock(symbol)
                }
        except Exception as e:
            logger.error(f"Error fetching trending {symbol}: {e}")
        return None
    
    tasks = [fetch_trending(symbol) for symbol in symbols]
    results = await asyncio.gather(*tasks)
    trending_data = [r for r in results if r is not None]
    
    response = {"trending": trending_data}
    
    if use_cache:
        stock_cache.set(cache_key, response)
    
    return response

@app.get("/api/search/{query}")
async def search_stocks(query: str):
    """Search for stocks (including Indian stocks)"""
    if len(query) < 2:
        return {"results": []}
    
    stock_db = {
        # US Stocks
        "AAPL": "Apple Inc.",
        "MSFT": "Microsoft Corporation",
        "GOOGL": "Alphabet Inc.",
        "AMZN": "Amazon.com Inc.",
        "TSLA": "Tesla Inc.",
        "NVDA": "NVIDIA Corporation",
        "META": "Meta Platforms Inc.",
        "JPM": "JPMorgan Chase & Co.",
        "V": "Visa Inc.",
        "JNJ": "Johnson & Johnson",
        "WMT": "Walmart Inc.",
        "PG": "Procter & Gamble Co.",
        "DIS": "The Walt Disney Company",
        "NFLX": "Netflix Inc.",
        "ADBE": "Adobe Inc.",
        "PYPL": "PayPal Holdings Inc.",
        "INTC": "Intel Corporation",
        "CSCO": "Cisco Systems Inc.",
        "PFE": "Pfizer Inc.",
        "XOM": "Exxon Mobil Corporation",
        "BAC": "Bank of America Corp",
        "KO": "The Coca-Cola Company",
        "PEP": "PepsiCo Inc.",
        "NKE": "Nike Inc.",
        
        # Indian Stocks
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
        "TITAN.NS": "Titan Company Ltd"
    }
    
    query_upper = query.upper()
    results = []
    
    for symbol, name in stock_db.items():
        display_symbol = normalize_indian_symbol(symbol)
        if query_upper in display_symbol or query_upper in name.upper():
            results.append({
                "symbol": display_symbol,
                "original_symbol": symbol,
                "name": name,
                "match_type": "symbol" if query_upper in display_symbol else "name",
                "is_indian": is_indian_stock(symbol)
            })
    
    results.sort(key=lambda x: (
        0 if x['match_type'] == 'symbol' and x['symbol'] == query_upper else
        1 if x['match_type'] == 'symbol' else 2,
        x['symbol']
    ))
    
    return {"results": results[:15]}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
        workers=4
    )