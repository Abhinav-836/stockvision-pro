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

def _is_number(value) -> bool:
    """True for real, finite ints/floats (bools and NaN excluded)."""
    if value is None or isinstance(value, bool):
        return False
    if not isinstance(value, (int, float)):
        return False
    return value == value and value not in (float('inf'), float('-inf'))


def normalize_percentage(value: Optional[float]) -> Optional[float]:
    """
    CORRECTLY normalize yFinance percentage values.

    yFinance returns values in THREE possible formats:
    1. Decimal: 0.0038 = 0.38% (dividend yield)
    2. Percentage: 15.7 = 15.7% (revenue growth)
    3. Ratio: 1.52 = 152% (ROE - needs *100)

    This function intelligently detects which format.

    FIXED: every range check below used to start at 0, so ANY negative
    value (a shrinking company's revenue growth of -0.05, a loss-maker's
    negative earnings growth) fell straight through to the "suspicious
    value" branch and came back as None. The UI then showed declining
    companies as "no data" instead of "-5.0%", and the AI score/growth
    label silently treated a real decline as missing. The magnitude is now
    normalized and the sign re-applied afterwards.
    """
    if not _is_number(value):
        return None

    sign = -1 if value < 0 else 1
    magnitude = abs(value)

    # Case 1: Small decimal (0.0001 to 1.0) - treat as decimal rate
    # Example: 0.0038 (dividend) → 0.38%
    if magnitude <= 1:
        return round(sign * magnitude * 100, 2)

    # Case 2: Small value between 1-10 could be a ratio (1.52 = 152% for ROE)
    # Must be checked BEFORE the general percentage range
    if magnitude <= 10:
        return round(sign * magnitude * 100, 2)

    # Case 3/4: Already a percentage (10% to 1000%)
    if magnitude <= 1000:
        return round(sign * magnitude, 2)

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
    if not _is_number(value):
        return None

    # FIXED: negative ROE/ROA (any loss-making company) used to return
    # None because every branch required value >= 0 — the UI showed
    # "N/A" instead of the real negative return. Sign is now preserved.
    sign = -1 if value < 0 else 1
    magnitude = abs(value)

    # If value is between 0-1, it's a ratio (0.15 = 15%)
    if magnitude <= 1:
        return round(sign * magnitude * 100, 2)

    # If value is between 1-10, it's likely a ratio (1.52 = 152%)
    if magnitude <= 10:
        return round(sign * magnitude * 100, 2)

    # Already percentage
    if magnitude <= 500:
        return round(sign * magnitude, 2)

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

    FIXED: yFinance's debtToEquity is ALWAYS a percentage (AAPL ~150 means
    1.5x, a low-debt company's 5.3 means 0.053x). The old code guessed
    "values above 10 are percentages, values at or below 10 are already
    ratios" — so every low-debt company (D/E under 10%) was shown with
    100x its real leverage (0.05 displayed as 5.3), scored 1/10 on
    financial health and labeled "High Risk". yFinance is the only tier
    that ever supplies this field (Alpha Vantage, Finnhub and NSE have no
    D/E at all), so it is always divided by 100.
    """
    try:
        de = info.get('debtToEquity')
        if _is_number(de):
            return round(float(de) / 100, 2)
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
    """Dividend yield as a percentage.

    FIXED: Yahoo changed dividendYield from a decimal (0.0044 = 0.44%) to
    an already-multiplied percentage (0.44 = 0.44%) in early 2025, and the
    pinned yfinance 0.2.66 returns the new format. normalize_dividend_yield
    can't tell those apart for small yields — a real 0.15% yield (sent as
    0.15) falls in its "decimal" range and was shown as 15%, which also
    earned it the "dividend trap" penalty in the AI score.

    The unambiguous source is annual dividend per share divided by price,
    so that is used whenever both are present. The old heuristic is only
    the fallback (Alpha Vantage's DividendYield, which is still a decimal,
    lands there and is handled correctly by it).
    """
    try:
        rate = info.get('dividendRate')
        if rate is None:
            rate = info.get('trailingAnnualDividendRate')
        price = info.get('currentPrice') or info.get('regularMarketPrice') or info.get('previousClose')
        if _is_number(rate) and _is_number(price) and price > 0:
            if rate == 0:
                return 0.0
            computed = rate / price * 100
            if 0 <= computed <= 25:
                return round(computed, 2)

        dy = info.get('dividendYield')
        if _is_number(dy):
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
    """
    Revenue and earnings growth metrics from yFinance info.

    FIXED: this used to return whatever normalize_percentage() produced,
    which passed None through when a value was missing — that was fine —
    BUT yFinance also sometimes returns strings like "29.7%" or "%" for
    growth fields (particularly for Indian tickers where the data feed
    is less consistent), and normalize_percentage() rejects any non-
    numeric input by returning None, so the field was dropped. The
    frontend then tried to render "Earnings Growth: " with no number,
    producing the "Earnings Growth: %" artifact.

    Now every value goes through a small _clean() helper that:
    - Accepts real numbers (int/float)
    - Accepts numeric strings like "29.7" or "29.7%" (strips the %)
    - Returns None for anything else (including "", "%", "-", "N/A")
    - Never emits a bare "%" or an empty string

    Also fixed: `is_growing` used to be `(rev_g or 0) > 0.05 and
    (earn_g or 0) > 0.05`, which silently treated a MISSING growth value
    as 0% and made every stock with no earnings-growth data look like it
    was "not growing". Now both values must be genuinely present and
    above 5% for the flag to be True.
    """
    try:
        info = stock.info if hasattr(stock, 'info') else {}

        rev_g  = info.get('revenueGrowth')
        earn_g = info.get('earningsGrowth')
        eq_g   = info.get('earningsQuarterlyGrowth')

        def _clean(v):
            """Return a properly-normalized percentage float, or None."""
            if v is None:
                return None
            if isinstance(v, bool):
                return None
            if isinstance(v, str):
                # Strip a stray "%" and any whitespace before parsing
                v = v.replace('%', '').strip()
                if not v:
                    return None
                try:
                    v = float(v)
                except (TypeError, ValueError):
                    return None
            if not isinstance(v, (int, float)):
                return None
            if isinstance(v, float) and (v != v):  # NaN check
                return None
            return normalize_percentage(v)

        result = {
            "revenue_growth":              _clean(rev_g),
            "earnings_growth":             _clean(earn_g),
            "earnings_quarterly_growth":   _clean(eq_g),
        }

        rg = result["revenue_growth"]
        eg = result["earnings_growth"]
        result["is_growing"] = (
            rg is not None and eg is not None and rg > 5 and eg > 5
        )
        return result

    except Exception as e:
        logger.error(f"Error analyzing growth: {e}")
        return {}


def get_ownership_pattern(stock) -> Dict:
    """Institutional / insider ownership and short interest.

    FIXED: info.get(key, 0) only falls back to 0 when the key is ABSENT.
    Yahoo frequently sends the key with a null value (very common for
    Indian tickers), so float(None) raised and the whole ownership block
    came back empty. `or 0` covers both cases.
    """
    try:
        info = stock.info if hasattr(stock, 'info') else {}
        return {
            "institutional_holders": round(float(info.get('heldPercentInstitutions') or 0) * 100, 2),
            "insider_holders":       round(float(info.get('heldPercentInsiders') or 0) * 100, 2),
            "short_percent":         round(float(info.get('shortPercentOfFloat') or 0) * 100, 2),
            "shares_outstanding":    int(info.get('sharesOutstanding') or 0),
        }
    except Exception as e:
        logger.error(f"Error getting ownership pattern: {e}")
        return {}


# ---------------------------------------------------------------------------
# News
# ---------------------------------------------------------------------------

def _parse_news_time(ts) -> Optional[datetime]:
    if ts is None:
        return None
    if isinstance(ts, (int, float)) and not isinstance(ts, bool):
        return datetime.fromtimestamp(ts, tz=timezone.utc).replace(tzinfo=None)
    if isinstance(ts, datetime):
        return ts.replace(tzinfo=None) if ts.tzinfo else ts
    if isinstance(ts, str):
        try:
            dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
            return dt.replace(tzinfo=None) if dt.tzinfo else dt
        except ValueError:
            return None
    return None


def parse_news_items(raw_items, max_news: int = 5) -> List[Dict]:
    """Normalize yFinance news items into {title, publisher, link, published}.

    FIXED: Yahoo moved news to a new schema in 2025 and the pinned
    yfinance 0.2.66 returns it: every item is now
    {"id": ..., "content": {"title", "pubDate", "provider": {"displayName"},
    "canonicalUrl": {"url"}}} instead of the old flat
    {"title", "publisher", "link", "providerPublishTime"}. The old parser
    read item["title"] on the outer dict, got "", and skipped every single
    item — so news was ALWAYS empty, and the AI thesis/sentiment prompts
    were built with no headlines at all. Both schemas are handled now.
    """
    formatted: List[Dict] = []
    for item in (raw_items or [])[:max_news * 3]:
        try:
            if not isinstance(item, dict):
                continue
            content = item.get('content') if isinstance(item.get('content'), dict) else None

            if content:
                title = (content.get('title') or '').strip()
                provider = content.get('provider') or {}
                publisher = provider.get('displayName') if isinstance(provider, dict) else None
                link = ((content.get('canonicalUrl') or {}).get('url')
                        or (content.get('clickThroughUrl') or {}).get('url') or '')
                published = _parse_news_time(content.get('pubDate') or content.get('displayTime'))
            else:
                title = (item.get('title') or '').strip()
                publisher = item.get('publisher')
                link = item.get('link') or ''
                published = _parse_news_time(item.get('providerPublishTime'))

            if not title or title.lower() in ('untitled', 'news'):
                continue

            formatted.append({
                "title":     title,
                "publisher": publisher or 'Unknown',
                "link":      link,
                "published": published.isoformat() if published else None,
            })
            if len(formatted) >= max_news:
                break
        except Exception as e:
            logger.debug(f"Skipping malformed news item: {e}")
            continue
    return formatted


def get_latest_news(symbol: str, max_news: int = 5) -> List[Dict]:
    """Fetch latest news headlines from yFinance.

    NOTE: this is a BLOCKING network call. Never call it directly from an
    async endpoint — main.py wraps it in fetch_news_async(), which runs it
    in a worker thread with a timeout.
    """
    try:
        import yfinance as yf
        stock = yf.Ticker(symbol)
        news  = getattr(stock, 'news', None) or []
        parsed = parse_news_items(news, max_news)
        # Diagnostics: an empty result used to be silent, which made it
        # impossible to tell "Yahoo returned nothing" from "Yahoo returned
        # items in a shape the parser doesn't understand".
        if not news:
            logger.info(f"yFinance returned no news items for {symbol}")
        elif not parsed:
            first = news[0] if isinstance(news[0], dict) else {}
            logger.warning(
                f"yFinance returned {len(news)} news items for {symbol} but none parsed; "
                f"first item keys: {list(first.keys())[:10]}"
            )
        return parsed
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