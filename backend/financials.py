# backend/financials.py
import numpy as np
import pandas as pd
from typing import Dict, Optional, List, Union
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

def calculate_pe_ratio(info: Dict) -> Optional[float]:
    """Calculate Price to Earnings ratio"""
    try:
        pe = info.get('trailingPE') or info.get('forwardPE')
        if pe and isinstance(pe, (int, float)) and pe > 0:
            return round(float(pe), 2)
        return None
    except (ValueError, TypeError):
        return None

def calculate_pb_ratio(info: Dict) -> Optional[float]:
    """Calculate Price to Book ratio"""
    try:
        pb = info.get('priceToBook')
        if pb and isinstance(pb, (int, float)) and pb > 0:
            return round(float(pb), 2)
        return None
    except (ValueError, TypeError):
        return None

def calculate_debt_to_equity(info: Dict) -> Optional[float]:
    """Calculate Debt to Equity ratio"""
    try:
        de = info.get('debtToEquity')
        if de and isinstance(de, (int, float)):
            return round(float(de) / 100, 2)
        return None
    except (ValueError, TypeError):
        return None

def calculate_current_ratio(info: Dict) -> Optional[float]:
    """Calculate Current Ratio"""
    try:
        current_ratio = info.get('currentRatio')
        if current_ratio and isinstance(current_ratio, (int, float)):
            return round(float(current_ratio), 2)
        return None
    except (ValueError, TypeError):
        return None

def calculate_roe(info: Dict) -> Optional[float]:
    """Calculate Return on Equity"""
    try:
        roe = info.get('returnOnEquity')
        if roe and isinstance(roe, (int, float)):
            return round(float(roe) * 100, 2)
        return None
    except (ValueError, TypeError):
        return None

def calculate_roa(info: Dict) -> Optional[float]:
    """Calculate Return on Assets"""
    try:
        roa = info.get('returnOnAssets')
        if roa and isinstance(roa, (int, float)):
            return round(float(roa) * 100, 2)
        return None
    except (ValueError, TypeError):
        return None

def get_dividend_yield(info: Dict) -> Optional[float]:
    """Get Dividend Yield percentage"""
    try:
        div_yield = info.get('dividendYield')
        if div_yield and isinstance(div_yield, (int, float)):
            return round(float(div_yield) * 100, 2)
        return None
    except (ValueError, TypeError):
        return None

def calculate_eps(info: Dict) -> Optional[float]:
    """Calculate Earnings Per Share"""
    try:
        eps = info.get('trailingEps') or info.get('forwardEps')
        if eps and isinstance(eps, (int, float)):
            return round(float(eps), 2)
        return None
    except (ValueError, TypeError):
        return None

def calculate_volatility(hist: pd.DataFrame) -> float:
    """Calculate stock volatility"""
    try:
        if hist is None or hist.empty or len(hist) < 20:
            return 1.0
        
        returns = hist['Close'].pct_change().dropna()
        if len(returns) < 20:
            return 1.0
            
        volatility = float(returns.std() * np.sqrt(252))
        return round(max(0.1, min(volatility, 5.0)), 2)
    except Exception as e:
        logger.error(f"Error calculating volatility: {e}")
        return 1.0

def calculate_technical_indicators(hist: pd.DataFrame) -> Dict:
    """Calculate technical indicators"""
    try:
        if hist is None or hist.empty or len(hist) < 50:
            return {}
        
        df = hist.copy()
        
        # Simple Moving Averages
        df['SMA_20'] = df['Close'].rolling(window=20).mean()
        df['SMA_50'] = df['Close'].rolling(window=50).mean()
        df['SMA_200'] = df['Close'].rolling(window=200).mean()
        
        # RSI
        delta = df['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss.replace(0, np.nan)
        rsi = 100 - (100 / (1 + rs))
        
        # MACD
        exp1 = df['Close'].ewm(span=12, adjust=False).mean()
        exp2 = df['Close'].ewm(span=26, adjust=False).mean()
        macd = exp1 - exp2
        signal = macd.ewm(span=9, adjust=False).mean()
        histogram = macd - signal
        
        current_price = df['Close'].iloc[-1]
        
        def safe_round(series, default=None):
            val = series.iloc[-1] if not series.empty else None
            return round(float(val), 2) if val is not None and not pd.isna(val) else default
        
        sma_20 = safe_round(df['SMA_20'])
        sma_50 = safe_round(df['SMA_50'])
        sma_200 = safe_round(df['SMA_200'])
        current_rsi = safe_round(rsi, 50)
        macd_val = safe_round(macd)
        signal_val = safe_round(signal)
        histogram_val = safe_round(histogram)
        
        # Determine trend
        trend = "Neutral"
        if sma_20 and sma_50:
            if current_price > sma_20 > sma_50:
                trend = "Strong Bullish"
            elif current_price > sma_20:
                trend = "Bullish"
            elif current_price < sma_20 < sma_50:
                trend = "Strong Bearish"
            elif current_price < sma_20:
                trend = "Bearish"
        
        return {
            "sma_20": sma_20,
            "sma_50": sma_50,
            "sma_200": sma_200,
            "rsi": current_rsi,
            "macd": macd_val,
            "signal": signal_val,
            "histogram": histogram_val,
            "price_vs_sma20": round(((current_price - sma_20) / sma_20) * 100, 2) if sma_20 else None,
            "price_vs_sma50": round(((current_price - sma_50) / sma_50) * 100, 2) if sma_50 else None,
            "trend": trend
        }
    except Exception as e:
        logger.error(f"Error calculating technical indicators: {e}")
        return {}

def analyze_growth(stock) -> Dict:
    """Analyze growth metrics"""
    try:
        info = stock.info if hasattr(stock, 'info') else {}
        
        revenue_growth = info.get('revenueGrowth')
        earnings_growth = info.get('earningsGrowth')
        earnings_quarterly_growth = info.get('earningsQuarterlyGrowth')
        
        result = {
            "revenue_growth": round(float(revenue_growth) * 100, 2) if revenue_growth else None,
            "earnings_growth": round(float(earnings_growth) * 100, 2) if earnings_growth else None,
            "earnings_quarterly_growth": round(float(earnings_quarterly_growth) * 100, 2) if earnings_quarterly_growth else None,
        }
        
        rev_growth_val = revenue_growth or 0
        earn_growth_val = earnings_growth or 0
        result["is_growing"] = rev_growth_val > 0.05 and earn_growth_val > 0.05
        
        return result
    except Exception as e:
        logger.error(f"Error analyzing growth: {e}")
        return {}

def get_ownership_pattern(stock) -> Dict:
    """Get ownership pattern information"""
    try:
        info = stock.info if hasattr(stock, 'info') else {}
        
        return {
            "institutional_holders": round(float(info.get('heldPercentInstitutions', 0)) * 100, 2),
            "insider_holders": round(float(info.get('heldPercentInsiders', 0)) * 100, 2),
            "short_percent": round(float(info.get('shortPercentOfFloat', 0)) * 100, 2),
            "shares_outstanding": int(info.get('sharesOutstanding', 0)),
        }
    except Exception as e:
        logger.error(f"Error getting ownership pattern: {e}")
        return {}

def get_latest_news(symbol: str, max_news: int = 5) -> List[Dict]:
    """Get latest news for the stock"""
    try:
        import yfinance as yf
        stock = yf.Ticker(symbol)
        news = stock.news if hasattr(stock, 'news') and stock.news else []
        
        formatted_news = []
        for item in news[:max_news]:
            try:
                publish_time = item.get('providerPublishTime')
                if publish_time:
                    if isinstance(publish_time, (int, float)):
                        publish_time = datetime.fromtimestamp(publish_time)
                    formatted_news.append({
                        "title": item.get('title', ''),
                        "publisher": item.get('publisher', ''),
                        "link": item.get('link', ''),
                        "published": publish_time.isoformat() if publish_time else None,
                    })
            except Exception as e:
                logger.debug(f"Error formatting news item: {e}")
                continue
        
        return formatted_news
    except Exception as e:
        logger.error(f"Error fetching news for {symbol}: {e}")
        return []

def calculate_ai_score(metrics: Dict) -> float:
    """
    Calculate AI-powered investment score (0-100)
    """
    score = 0
    
    # Valuation Score (25 points)
    pe_ratio = metrics.get('pe_ratio')
    pb_ratio = metrics.get('pb_ratio')
    
    if pe_ratio:
        if 10 <= pe_ratio <= 20:
            score += 15
        elif 20 < pe_ratio <= 25:
            score += 10
        elif pe_ratio < 10:
            score += 12
        elif 25 < pe_ratio <= 30:
            score += 5
        else:
            score += 2
    
    if pb_ratio:
        if pb_ratio < 1.5:
            score += 10
        elif pb_ratio < 2.5:
            score += 7
        elif pb_ratio < 4:
            score += 4
        else:
            score += 2
    
    # Profitability Score (25 points)
    roe = metrics.get('roe')
    roa = metrics.get('roa')
    eps = metrics.get('eps')
    
    if roe:
        if roe > 25:
            score += 10
        elif roe > 18:
            score += 8
        elif roe > 12:
            score += 6
        elif roe > 8:
            score += 4
        else:
            score += 2
    
    if roa:
        if roa > 10:
            score += 8
        elif roa > 7:
            score += 6
        elif roa > 4:
            score += 4
        elif roa > 2:
            score += 2
    
    if eps:
        if eps > 8:
            score += 7
        elif eps > 5:
            score += 5
        elif eps > 2:
            score += 3
        elif eps > 0:
            score += 1
    
    # Financial Health Score (20 points)
    debt_to_equity = metrics.get('debt_to_equity')
    current_ratio = metrics.get('current_ratio')
    
    if debt_to_equity is not None:
        if debt_to_equity < 0.3:
            score += 10
        elif debt_to_equity < 0.8:
            score += 8
        elif debt_to_equity < 1.5:
            score += 5
        elif debt_to_equity < 2.5:
            score += 3
        else:
            score += 1
    
    if current_ratio:
        if current_ratio >= 2.5:
            score += 10
        elif current_ratio >= 1.8:
            score += 8
        elif current_ratio >= 1.2:
            score += 5
        elif current_ratio >= 1:
            score += 3
        else:
            score += 1
    
    # Income Score (10 points)
    dividend_yield = metrics.get('dividend_yield')
    
    if dividend_yield:
        if dividend_yield >= 5:
            score += 10
        elif dividend_yield >= 3:
            score += 8
        elif dividend_yield >= 1.5:
            score += 5
        elif dividend_yield >= 0.5:
            score += 3
    
    # Risk Score (10 points)
    volatility = metrics.get('volatility', 1)
    
    if volatility < 0.6:
        score += 10
    elif volatility < 0.9:
        score += 8
    elif volatility < 1.2:
        score += 6
    elif volatility < 1.6:
        score += 4
    else:
        score += 2
    
    # Technical Indicators Score (10 points)
    technical = metrics.get('technical_indicators', {})
    rsi = technical.get('rsi')
    
    if rsi:
        if 45 <= rsi <= 55:
            score += 5
        elif 30 <= rsi <= 70:
            score += 3
        elif rsi < 30:
            score += 4  # Oversold - potential buy
        elif rsi > 70:
            score += 2  # Overbought - potential sell
    
    trend = technical.get('trend', '')
    if 'Strong Bullish' in trend:
        score += 5
    elif 'Bullish' in trend:
        score += 4
    elif 'Neutral' in trend:
        score += 2
    elif 'Bearish' in trend:
        score += 1
    
    return min(score, 100)

def generate_recommendation(ai_score: float, metrics: Dict) -> Dict:
    """
    Generate investment recommendation based on AI score
    """
    # Determine recommendation
    if ai_score >= 85:
        recommendation = "Strong Buy"
        confidence = "Very High"
    elif ai_score >= 75:
        recommendation = "Buy"
        confidence = "High"
    elif ai_score >= 65:
        recommendation = "Accumulate"
        confidence = "Moderate"
    elif ai_score >= 55:
        recommendation = "Hold"
        confidence = "Moderate"
    elif ai_score >= 45:
        recommendation = "Neutral"
        confidence = "Low"
    elif ai_score >= 35:
        recommendation = "Reduce"
        confidence = "Low"
    else:
        recommendation = "Avoid"
        confidence = "Very Low"
    
    # Determine risk level
    volatility = metrics.get('volatility', 1)
    debt_to_equity = metrics.get('debt_to_equity', 0)
    
    risk_score = 0
    if volatility > 1.5:
        risk_score += 2
    elif volatility > 1.2:
        risk_score += 1
    
    if debt_to_equity and debt_to_equity > 2:
        risk_score += 2
    elif debt_to_equity and debt_to_equity > 1:
        risk_score += 1
    
    if risk_score >= 3:
        risk_level = "High Risk"
    elif risk_score >= 1:
        risk_level = "Moderate Risk"
    else:
        risk_level = "Low Risk"
    
    # Determine growth potential
    roe = metrics.get('roe', 0)
    growth_metrics = metrics.get('growth_metrics', {})
    revenue_growth = growth_metrics.get('revenue_growth', 0)
    
    growth_score = 0
    if roe and roe > 20:
        growth_score += 2
    if revenue_growth and revenue_growth > 10:
        growth_score += 2
    
    if growth_score >= 3:
        growth_potential = "High Growth"
    elif growth_score >= 1:
        growth_potential = "Moderate Growth"
    else:
        growth_potential = "Low Growth"
    
    # Determine valuation
    pe_ratio = metrics.get('pe_ratio')
    
    if pe_ratio:
        if pe_ratio < 12:
            valuation = "Undervalued"
        elif pe_ratio < 20:
            valuation = "Fairly Valued"
        elif pe_ratio < 30:
            valuation = "Overvalued"
        else:
            valuation = "Significantly Overvalued"
    else:
        valuation = "Unable to determine"
    
    return {
        "recommendation": recommendation,
        "confidence": confidence,
        "risk_level": risk_level,
        "growth_potential": growth_potential,
        "valuation": valuation
    }

def is_indian_stock(symbol: str) -> bool:
    """Check if symbol is likely an Indian stock"""
    indian_suffixes = ['.NS', '.BO', '.NSE', '.BSE']
    return any(symbol.endswith(suffix) for suffix in indian_suffixes)

def normalize_indian_symbol(symbol: str) -> str:
    """Normalize Indian stock symbol for display"""
    suffixes = ['.NS', '.BO', '.NSE', '.BSE']
    for suffix in suffixes:
        if symbol.endswith(suffix):
            return symbol.replace(suffix, '').strip()
    return symbol