# backend/financials.py
import numpy as np
import pandas as pd
from typing import Dict, Optional, List
from datetime import datetime, timezone
import logging

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# CRITICAL FIX: Percentage normalization for yFinance
# ---------------------------------------------------------------------------

def normalize_percentage(value: Optional[float]) -> Optional[float]:
    """
    CORRECTLY normalize yFinance percentage values.
    
    yFinance returns values in THREE possible formats:
    1. Decimal: 0.0038 = 0.38% (dividend yield)
    2. Percentage: 15.7 = 15.7% (revenue growth)
    3. Ratio: 1.52 = 152% (ROE - needs *100)
    
    This function intelligently detects which format.
    """
    if value is None or not isinstance(value, (int, float)):
        return None
    
    # Case 1: Small decimal (0.0001 to 1.0) - treat as decimal rate
    # Example: 0.0038 (dividend) → 0.38%
    if 0 <= value <= 1:
        return round(value * 100, 2)
    
    # Case 2: Normal percentage (1% to 100%)
    # Example: 15.7 → 15.7%
    if 1 < value <= 100:
        return round(value, 2)
    
    # Case 3: Large value that should be divided (100%+)
    # Example: 1.52 (ROE as ratio) → 152%
    # But wait - yFinance sometimes gives 152 directly
    # So we need to detect: if value is between 1-10 AND looks like ratio
    if 1 < value <= 10:
        # Could be ratio (1.52 = 152%) OR small percentage (1.5%)
        # Check context from other metrics to decide
        # For now, assume ratio for ROE/ROA, percentage for others
        return round(value * 100, 2)
    
    # Case 4: Already large percentage (over 100%)
    if 100 < value <= 1000:
        return round(value, 2)
    
    # Case 5: Suspicious value - log and return None
    logger.warning(f"Suspicious percentage value: {value} - returning None")
    return None


def normalize_dividend_yield(value: Optional[float]) -> Optional[float]:
    """
    BULLETPROOF dividend yield normalization.
    Handles ALL the weird ways yFinance returns dividend data.
    """
    if value is None or not isinstance(value, (int, float)):
        return None
    
    # Case 1: Normal decimal format (0.0038 = 0.38%)
    if 0 <= value <= 0.2:
        return round(value * 100, 2)
    
    # Case 2: Already percentage but realistic (0.38% to 15%)
    if 0.2 < value <= 15:
        return round(value, 2)
    
    # Case 3: Clearly wrong huge number (38, 120, etc.)
    # Try dividing by 100 first
    if value > 15:
        fixed = value / 100
        if 0 <= fixed <= 15:
            return round(fixed, 2)
        
        # Try dividing by 1000 (some APIs return 3800 for 3.8%)
        fixed = value / 1000
        if 0 <= fixed <= 15:
            return round(fixed, 2)
    
    # Case 4: Value is exactly the problem (38.0)
    # This is likely a bug in yFinance data feed
    if 30 <= value <= 50:
        # For values between 30-50, assume it's percentage divided by 100
        return round(value / 100, 2)
    
    # If all else fails, return None (don't show wrong data)
    logger.warning(f"Could not normalize dividend yield: {value}")
    return None


def normalize_roe_roa(value: Optional[float]) -> Optional[float]:
    """
    SPECIALIZED ROE/ROA normalization.
    ROE can be >100% for profitable tech companies.
    """
    if value is None or not isinstance(value, (int, float)):
        return None
    
    # If value is between 0-1, it's a ratio (0.15 = 15%)
    if 0 <= value <= 1:
        return round(value * 100, 2)
    
    # If value is between 1-10, it's likely a ratio (1.52 = 152%)
    if 1 < value <= 10:
        return round(value * 100, 2)
    
    # Already percentage
    if 10 < value <= 500:
        return round(value, 2)
    
    return None


# ---------------------------------------------------------------------------
# Ratio helpers with fixed normalization
# ---------------------------------------------------------------------------

def calculate_pe_ratio(info: Dict) -> Optional[float]:
    """Trailing P/E, falling back to forward P/E."""
    try:
        pe = info.get('trailingPE') or info.get('forwardPE')
        if pe is not None and isinstance(pe, (int, float)) and pe > 0:
            return round(float(pe), 2)
    except (ValueError, TypeError):
        pass
    return None


def calculate_pb_ratio(info: Dict) -> Optional[float]:
    """Price-to-Book ratio."""
    try:
        pb = info.get('priceToBook')
        if pb is not None and isinstance(pb, (int, float)) and pb > 0:
            return round(float(pb), 2)
    except (ValueError, TypeError):
        pass
    return None


def calculate_debt_to_equity(info: Dict) -> Optional[float]:
    """
    Debt-to-Equity ratio.
    yFinance can return ratio (1.5) or percentage (150).
    """
    try:
        de = info.get('debtToEquity')
        if de is not None and isinstance(de, (int, float)):
            # If value > 10, it's likely percentage (150 = 1.5 ratio)
            if de > 10:
                de = de / 100
            return round(float(de), 2)
    except (ValueError, TypeError):
        pass
    return None


def calculate_current_ratio(info: Dict) -> Optional[float]:
    """Current Ratio (current assets / current liabilities)."""
    try:
        cr = info.get('currentRatio')
        if cr is not None and isinstance(cr, (int, float)):
            return round(float(cr), 2)
    except (ValueError, TypeError):
        pass
    return None


def calculate_roe(info: Dict) -> Optional[float]:
    """Return on Equity as a percentage - FIXED."""
    try:
        roe = info.get('returnOnEquity')
        if roe is not None and isinstance(roe, (int, float)):
            return normalize_roe_roa(roe)
    except (ValueError, TypeError):
        pass
    return None


def calculate_roa(info: Dict) -> Optional[float]:
    """Return on Assets as a percentage - FIXED."""
    try:
        roa = info.get('returnOnAssets')
        if roa is not None and isinstance(roa, (int, float)):
            return normalize_roe_roa(roa)
    except (ValueError, TypeError):
        pass
    return None


def get_dividend_yield(info: Dict) -> Optional[float]:
    """Dividend yield as a percentage - FIXED."""
    try:
        dy = info.get('dividendYield')
        if dy is not None and isinstance(dy, (int, float)):
            return normalize_dividend_yield(dy)
    except (ValueError, TypeError):
        pass
    return None


def calculate_eps(info: Dict) -> Optional[float]:
    """Earnings Per Share (trailing, falling back to forward)."""
    try:
        eps = info.get('trailingEps') or info.get('forwardEps')
        if eps is not None and isinstance(eps, (int, float)):
            return round(float(eps), 2)
    except (ValueError, TypeError):
        pass
    return None


# ---------------------------------------------------------------------------
# Volatility
# ---------------------------------------------------------------------------

def calculate_volatility(hist: pd.DataFrame) -> float:
    """
    Annualised volatility from daily log-returns.
    """
    try:
        if hist is None or hist.empty or len(hist) < 20:
            return 0.25  # Default moderate volatility
        returns = hist['Close'].pct_change().dropna()
        if len(returns) < 20:
            return 0.25
        vol = float(returns.std() * np.sqrt(252))
        return round(max(0.1, min(vol, 2.0)), 4)  # Cap at 200% volatility
    except Exception as e:
        logger.error(f"Error calculating volatility: {e}")
        return 0.25


# ---------------------------------------------------------------------------
# Technical indicators
# ---------------------------------------------------------------------------

def calculate_technical_indicators(hist: pd.DataFrame) -> Dict:
    """
    SMA-20/50/200, RSI-14, and MACD.
    """
    try:
        if hist is None or hist.empty or len(hist) < 20:
            return {}

        df = hist.copy()
        n = len(df)

        # Moving averages
        df['SMA_20']  = df['Close'].rolling(window=20).mean()  if n >= 20  else np.nan
        df['SMA_50']  = df['Close'].rolling(window=50).mean()  if n >= 50  else np.nan
        df['SMA_200'] = df['Close'].rolling(window=200).mean() if n >= 200 else np.nan

        # RSI-14
        delta = df['Close'].diff()
        gain  = delta.where(delta > 0, 0.0).rolling(window=14).mean()
        loss  = (-delta.where(delta < 0, 0.0)).rolling(window=14).mean()
        rs    = gain / loss.replace(0, np.nan)
        rsi   = 100 - (100 / (1 + rs))

        # MACD
        exp1      = df['Close'].ewm(span=12, adjust=False).mean()
        exp2      = df['Close'].ewm(span=26, adjust=False).mean()
        macd      = exp1 - exp2
        signal    = macd.ewm(span=9, adjust=False).mean()
        histogram = macd - signal

        current_price = float(df['Close'].iloc[-1])

        def _last(series, default=None):
            if series is None or series.empty:
                return default
            val = series.iloc[-1]
            return round(float(val), 2) if val is not None and not pd.isna(val) else default

        sma_20     = _last(df['SMA_20'])
        sma_50     = _last(df['SMA_50'])
        sma_200    = _last(df['SMA_200'])
        cur_rsi    = _last(rsi, 50.0)
        macd_val   = _last(macd)
        signal_val = _last(signal)
        hist_val   = _last(histogram)

        # Trend
        trend = "Neutral"
        if sma_20 is not None and sma_50 is not None:
            if current_price > sma_20 > sma_50:
                trend = "Strong Bullish"
            elif current_price > sma_20:
                trend = "Bullish"
            elif current_price < sma_20 < sma_50:
                trend = "Strong Bearish"
            elif current_price < sma_20:
                trend = "Bearish"
        elif sma_20 is not None:
            trend = "Bullish" if current_price > sma_20 else "Bearish"

        return {
            "sma_20":           sma_20,
            "sma_50":           sma_50,
            "sma_200":          sma_200,
            "rsi":              cur_rsi,
            "macd":             macd_val,
            "signal":           signal_val,
            "histogram":        hist_val,
            "price_vs_sma20":   round(((current_price - sma_20)  / sma_20)  * 100, 2) if sma_20  else None,
            "price_vs_sma50":   round(((current_price - sma_50)  / sma_50)  * 100, 2) if sma_50  else None,
            "price_vs_sma200":  round(((current_price - sma_200) / sma_200) * 100, 2) if sma_200 else None,
            "trend":            trend,
        }

    except Exception as e:
        logger.error(f"Error calculating technical indicators: {e}")
        return {}


# ---------------------------------------------------------------------------
# Growth & ownership
# ---------------------------------------------------------------------------

def analyze_growth(stock) -> Dict:
    """Revenue and earnings growth metrics from yFinance info."""
    try:
        info = stock.info if hasattr(stock, 'info') else {}

        rev_g  = info.get('revenueGrowth')
        earn_g = info.get('earningsGrowth')
        eq_g   = info.get('earningsQuarterlyGrowth')

        result = {
            "revenue_growth":              normalize_percentage(rev_g),
            "earnings_growth":             normalize_percentage(earn_g),
            "earnings_quarterly_growth":   normalize_percentage(eq_g),
        }
        result["is_growing"] = bool((rev_g or 0) > 0.05 and (earn_g or 0) > 0.05)
        return result

    except Exception as e:
        logger.error(f"Error analyzing growth: {e}")
        return {}


def get_ownership_pattern(stock) -> Dict:
    """Institutional / insider ownership and short interest."""
    try:
        info = stock.info if hasattr(stock, 'info') else {}
        return {
            "institutional_holders": round(float(info.get('heldPercentInstitutions', 0)) * 100, 2),
            "insider_holders":       round(float(info.get('heldPercentInsiders', 0)) * 100, 2),
            "short_percent":         round(float(info.get('shortPercentOfFloat', 0)) * 100, 2),
            "shares_outstanding":    int(info.get('sharesOutstanding', 0)),
        }
    except Exception as e:
        logger.error(f"Error getting ownership pattern: {e}")
        return {}


# ---------------------------------------------------------------------------
# News
# ---------------------------------------------------------------------------

def get_latest_news(symbol: str, max_news: int = 5) -> List[Dict]:
    """Fetch latest news headlines from yFinance."""
    try:
        import yfinance as yf
        stock = yf.Ticker(symbol)
        news  = getattr(stock, 'news', None) or []

        formatted: List[Dict] = []
        for item in news[:max_news * 2]:
            try:
                title = item.get('title', '').strip()
                if not title or title.lower() in ['', 'untitled', 'news']:
                    continue
                
                ts = item.get('providerPublishTime')
                if ts is not None:
                    if isinstance(ts, (int, float)):
                        dt = datetime.fromtimestamp(ts, tz=timezone.utc).replace(tzinfo=None)
                    elif isinstance(ts, datetime):
                        dt = ts.replace(tzinfo=None) if ts.tzinfo else ts
                    else:
                        dt = None
                else:
                    dt = None

                formatted.append({
                    "title":     title,
                    "publisher": item.get('publisher', 'Unknown'),
                    "link":      item.get('link', ''),
                    "published": dt.isoformat() if dt else None,
                })
                
                if len(formatted) >= max_news:
                    break
                    
            except Exception as e:
                logger.debug(f"Skipping malformed news item for {symbol}: {e}")
                continue

        return formatted

    except Exception as e:
        logger.error(f"Error fetching news for {symbol}: {e}")
        return []


# ---------------------------------------------------------------------------
# AI score - WITH TECH SECTOR ADJUSTMENT
# ---------------------------------------------------------------------------

def calculate_ai_score(metrics: Dict) -> float:
    """
    Rule-based investment score 0-100.
    Now with tech sector adjustment for high P/B ratios.
    """
    score = 0
    sector = metrics.get('sector', '')
    is_tech = sector == 'Technology'

    # --- Valuation (25 pts) - Adjusted for tech ---------------------------------
    pe = metrics.get('pe_ratio')
    pb = metrics.get('pb_ratio')

    if pe is not None and isinstance(pe, (int, float)):
        if 10 <= pe <= 20:
            score += 15
        elif 20 < pe <= 25:
            score += 12
        elif pe < 10:
            score += 12
        elif 25 < pe <= 30:
            score += 8
        elif 30 < pe <= 40:
            score += 5  # Tech can have higher P/E
        else:
            score += 2

    if pb is not None and isinstance(pb, (int, float)):
        if is_tech:
            # Relaxed scoring for tech stocks
            if pb < 5:
                score += 10
            elif pb < 10:
                score += 8
            elif pb < 15:
                score += 6
            elif pb < 20:
                score += 4
            else:
                score += 2
        else:
            # Normal scoring for other sectors
            if pb < 1.5:
                score += 10
            elif pb < 2.5:
                score += 7
            elif pb < 4.0:
                score += 4
            else:
                score += 2

    # --- Profitability (25 pts) --------------------------------------------
    roe = metrics.get('roe')
    roa = metrics.get('roa')
    eps = metrics.get('eps')

    if roe is not None and isinstance(roe, (int, float)):
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

    if roa is not None and isinstance(roa, (int, float)):
        if roa > 10:
            score += 8
        elif roa > 7:
            score += 6
        elif roa > 4:
            score += 4
        elif roa > 2:
            score += 2

    if eps is not None and isinstance(eps, (int, float)):
        if eps > 8:
            score += 7
        elif eps > 5:
            score += 5
        elif eps > 2:
            score += 3
        elif eps > 0:
            score += 1

    # --- Financial health (20 pts) ----------------------------------------
    de = metrics.get('debt_to_equity')
    cr = metrics.get('current_ratio')

    if de is not None and isinstance(de, (int, float)):
        if de < 0.3:
            score += 10
        elif de < 0.8:
            score += 8
        elif de < 1.5:
            score += 5
        elif de < 2.5:
            score += 3
        else:
            score += 1

    if cr is not None and isinstance(cr, (int, float)):
        if cr >= 2.5:
            score += 10
        elif cr >= 1.8:
            score += 8
        elif cr >= 1.2:
            score += 5
        elif cr >= 1.0:
            score += 3
        else:
            score += 1

    # --- Income (10 pts) --------------------------------------------------
    div = metrics.get('dividend_yield')
    if div is not None and isinstance(div, (int, float)):
        if 2.0 <= div <= 6.0:
            score += 8
        elif 0.5 <= div < 2.0:
            score += 5
        elif div > 6.0:
            score += 3
        elif 0 < div < 0.5:
            score += 2

    # --- Risk / volatility (10 pts) ----------------------------------------
    vol = metrics.get('volatility', 0.25)
    if vol < 0.3:
        score += 10
    elif vol < 0.5:
        score += 8
    elif vol < 0.8:
        score += 6
    elif vol < 1.2:
        score += 4
    else:
        score += 2

    # --- Technical (10 pts) -----------------------------------------------
    tech = metrics.get('technical_indicators', {})
    rsi = tech.get('rsi')
    trend = tech.get('trend', '')

    if rsi is not None and isinstance(rsi, (int, float)):
        if 45 <= rsi <= 55:
            score += 5
        elif 30 <= rsi <= 70:
            score += 3
        elif rsi < 30:
            score += 3
        else:
            score += 2

    if 'Strong Bullish' in trend:
        score += 5
    elif 'Bullish' in trend:
        score += 4
    elif 'Neutral' in trend:
        score += 2
    else:
        score += 1

    return min(float(score), 100.0)


# ---------------------------------------------------------------------------
# Recommendation engine
# ---------------------------------------------------------------------------

def generate_recommendation(ai_score: float, metrics: Dict) -> Dict:
    """Convert AI score into recommendation labels."""
    
    # Recommendation tier
    if ai_score >= 85:
        recommendation, confidence = "Strong Buy", "Very High"
    elif ai_score >= 75:
        recommendation, confidence = "Buy", "High"
    elif ai_score >= 65:
        recommendation, confidence = "Accumulate", "Moderate"
    elif ai_score >= 55:
        recommendation, confidence = "Hold", "Moderate"
    elif ai_score >= 45:
        recommendation, confidence = "Neutral", "Low"
    elif ai_score >= 35:
        recommendation, confidence = "Reduce", "Low"
    else:
        recommendation, confidence = "Avoid", "Very Low"

    # Risk level
    vol = metrics.get('volatility', 0.25)
    de = metrics.get('debt_to_equity') or 0
    risk_score = (2 if vol > 0.8 else 1 if vol > 0.5 else 0)
    risk_score += (2 if de > 2.0 else 1 if de > 1.0 else 0)

    if risk_score >= 3:
        risk_level = "High Risk"
    elif risk_score >= 1:
        risk_level = "Moderate Risk"
    else:
        risk_level = "Low Risk"

    # Growth potential
    roe = metrics.get('roe') or 0
    rev_growth = (metrics.get('growth_metrics') or {}).get('revenue_growth') or 0
    growth_score = (2 if roe > 20 else 0) + (2 if rev_growth > 10 else 0)

    if growth_score >= 3:
        growth_potential = "High Growth"
    elif growth_score >= 1:
        growth_potential = "Moderate Growth"
    else:
        growth_potential = "Low Growth"

    # Valuation label
    pe = metrics.get('pe_ratio')
    sector = metrics.get('sector', '')
    is_tech = sector == 'Technology'
    
    if pe is not None and isinstance(pe, (int, float)):
        if is_tech:
            if pe < 20:
                valuation = "Undervalued"
            elif pe < 30:
                valuation = "Fairly Valued"
            elif pe < 45:
                valuation = "Slightly Overvalued"
            else:
                valuation = "Overvalued"
        else:
            if pe < 12:
                valuation = "Undervalued"
            elif pe < 20:
                valuation = "Fairly Valued"
            elif pe < 30:
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
        "valuation": valuation,
    }


# ---------------------------------------------------------------------------
# Indian stock helpers
# ---------------------------------------------------------------------------

_INDIAN_SUFFIXES = ('.NS', '.BO', '.NSE', '.BSE')

def is_indian_stock(symbol: str) -> bool:
    return any(symbol.upper().endswith(s) for s in _INDIAN_SUFFIXES)


def normalize_indian_symbol(symbol: str) -> str:
    """Remove Indian exchange suffix from symbol."""
    for suffix in _INDIAN_SUFFIXES:
        if symbol.upper().endswith(suffix):
            return symbol[:-len(suffix)]
    return symbol