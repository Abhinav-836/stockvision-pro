# backend/ai_service.py  — ENHANCED VERSION
import os
import json
import logging
import asyncio
import time
import re
from typing import Dict, Optional, List
from datetime import datetime
from collections import defaultdict
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)


class RateLimiter:
    def __init__(self, max_requests=10, time_window=60):
        self.max_requests = max_requests
        self.time_window = time_window
        self.requests: Dict[str, list] = defaultdict(list)
        self.total_requests = 0
        self.daily_requests: Dict[str, int] = defaultdict(int)
        self.daily_limit = 500

    def can_make_request(self, user_id="default") -> bool:
        now = time.time()
        self.requests[user_id] = [t for t in self.requests[user_id] if now - t < self.time_window]
        if len(self.requests[user_id]) >= self.max_requests:
            logger.warning(f"Rate limit exceeded for user {user_id}")
            return False
        today = datetime.now().strftime("%Y-%m-%d")
        if self.daily_requests[today] >= self.daily_limit:
            logger.warning(f"Daily AI limit reached: {self.daily_limit}")
            return False
        self.requests[user_id].append(now)
        self.daily_requests[today] += 1
        self.total_requests += 1
        return True

    def get_stats(self) -> Dict:
        today = datetime.now().strftime("%Y-%m-%d")
        return {
            "total_requests": self.total_requests,
            "daily_requests": self.daily_requests[today],
            "daily_limit": self.daily_limit,
            "active_users": len(self.requests)
        }


class OpenRouterAIService:
    def __init__(self):
        self.api_key  = os.getenv("OPENROUTER_API_KEY")
        self.base_url = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
        self.model    = os.getenv("OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct:free")
        # Use app URL from env for production; fallback to localhost for development
        self.app_url  = os.getenv("APP_URL", "http://localhost:5173")

        if not self.api_key:
            logger.warning("OPENROUTER_API_KEY not set — AI features will use fallback mode.")
            self.client = None
        else:
            self.client = OpenAI(
                base_url=self.base_url,
                api_key=self.api_key,
                default_headers={
                    "HTTP-Referer": self.app_url,
                    "X-Title": "StockVision Pro"
                }
            )

        self.rate_limiter = RateLimiter(max_requests=10, time_window=60)
        self.cache: Dict[str, tuple] = {}
        self.cache_ttl = int(os.getenv("AI_CACHE_TTL", 900))  # 15 min
        logger.info(f"OpenRouter AI Service ready — model: {self.model}")

    # ------------------------------------------------------------------
    # Core query
    # ------------------------------------------------------------------
    async def query(self,
                    prompt: str,
                    system_prompt: Optional[str] = None,
                    temperature: float = 0.3,
                    max_tokens: int = 800) -> Optional[str]:
        if not self.client:
            return None

        cache_key = f"{prompt[:120]}|{system_prompt[:80] if system_prompt else ''}"
        if cache_key in self.cache:
            cached_time, cached_resp = self.cache[cache_key]
            if (datetime.now() - cached_time).total_seconds() < self.cache_ttl:
                logger.debug("AI cache hit")
                return cached_resp

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        try:
            completion = await asyncio.wait_for(
                asyncio.to_thread(
                    lambda: self.client.chat.completions.create(
                        model=self.model,
                        messages=messages,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        top_p=0.7,
                    )
                ),
                timeout=28.0
            )
            response = completion.choices[0].message.content
            self.cache[cache_key] = (datetime.now(), response)
            return response
        except asyncio.TimeoutError:
            logger.error("OpenRouter API timeout")
            return None
        except Exception as e:
            logger.error(f"OpenRouter API error: {e}")
            return None

    async def query_with_retry(self,
                               prompt: str,
                               system_prompt: Optional[str] = None,
                               temperature: float = 0.3,
                               max_tokens: int = 800,
                               max_retries: int = 2,
                               user_id: str = "anonymous") -> Optional[str]:
        if not self.rate_limiter.can_make_request(user_id):
            logger.warning(f"AI rate limit hit for user {user_id}")
            return None

        for attempt in range(max_retries):
            response = await self.query(prompt, system_prompt, temperature, max_tokens)
            if response:
                return response
            if attempt < max_retries - 1:
                await asyncio.sleep(2 ** attempt)

        logger.error(f"All {max_retries} AI attempts failed")
        return None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _extract_json(text: str) -> Optional[Dict]:
        """Extract first JSON object from a string."""
        try:
            match = re.search(r'\{.*\}', text, re.DOTALL)
            if match:
                return json.loads(match.group())
        except (json.JSONDecodeError, AttributeError):
            pass
        return None

    # ------------------------------------------------------------------
    # Public methods
    # ------------------------------------------------------------------
    async def analyze_stock_comparison(self, stocks_data: List[Dict], user_id: str = "anonymous") -> Dict:
        summaries = []
        for stock in stocks_data:
            symbol  = stock.get('symbol', 'N/A')
            company = stock.get('company_name', 'N/A')
            price   = stock.get('current_price', 0) or 0
            change  = stock.get('change_percent', 0) or 0
            pe      = stock.get('pe_ratio', 'N/A')
            roe     = stock.get('roe', 'N/A')
            debt    = stock.get('debt_to_equity', 'N/A')
            div     = stock.get('dividend_yield', 'N/A')
            mcap    = (stock.get('market_cap', 0) or 0) / 1e9
            score   = stock.get('ai_score', 0)
            rec     = stock.get('recommendation', 'N/A')
            # Safe formatting
            summaries.append(
                f"{symbol} ({company}): Price=${price:.2f}, Change={change:+.2f}%, "
                f"P/E={pe}, ROE={roe}%, D/E={debt}, Div={div}%, "
                f"MCap=${mcap:.1f}B, Score={score}/100, Rec={rec}"
            )

        system_prompt = (
            "You are a professional financial analyst. "
            "Compare the given stocks objectively. "
            "Return ONLY valid JSON, no markdown or extra text."
        )
        prompt = (
            "Analyze these stocks:\n\n" +
            "\n".join(summaries) +
            "\n\nReturn JSON with EXACTLY these fields:\n"
            "best_for_growth, best_for_value, best_for_income, safest_option, "
            "most_volatile, overall_recommendation (all strings — stock symbol), "
            "analysis (2-3 sentence summary), risk_assessment (2-3 sentence risk analysis), "
            "investment_tips (array of 3 short tip strings)."
        )

        response = await self.query_with_retry(prompt, system_prompt, temperature=0.2, user_id=user_id)
        if response:
            parsed = self._extract_json(response)
            if parsed:
                return parsed

        return self._fallback_comparison(stocks_data)

    async def generate_investment_thesis(self, stock_data: Dict, news: List[Dict], user_id: str = "anonymous") -> Dict:
        symbol  = stock_data.get('symbol', 'N/A')
        company = stock_data.get('company_name', 'N/A')
        price   = stock_data.get('current_price', 'N/A')
        pe      = stock_data.get('pe_ratio', 'N/A')
        roe     = stock_data.get('roe', 'N/A')
        debt    = stock_data.get('debt_to_equity', 'N/A')
        div     = stock_data.get('dividend_yield', 'N/A')
        score   = stock_data.get('ai_score', 'N/A')
        rec     = stock_data.get('recommendation', 'N/A')
        news_summary = "\n".join([f"- {n.get('title', '')}" for n in news[:5]])

        system_prompt = (
            "You are a professional financial analyst writing an investment thesis. "
            "Return ONLY valid JSON, no markdown or extra text."
        )
        prompt = (
            f"Create a detailed investment thesis for {symbol} ({company}):\n\n"
            f"Price=${price}, P/E={pe}, ROE={roe}%, D/E={debt}, Div={div}%, "
            f"Score={score}/100, Rec={rec}\n\nRecent news:\n{news_summary}\n\n"
            "Return JSON with: thesis (string), strengths (array[3]), weaknesses (array[2]), "
            "risks (array[3]), outlook (string), catalyst (string), "
            "valuation_opinion (string: undervalued/fairly valued/overvalued), action (Buy/Hold/Sell)."
        )

        response = await self.query_with_retry(prompt, system_prompt, temperature=0.3, user_id=user_id)
        if response:
            parsed = self._extract_json(response)
            if parsed:
                return parsed

        return self._fallback_thesis(stock_data)

    async def answer_question(self, question: str, stock_data: Optional[Dict] = None, user_id: str = "anonymous") -> str:
        context = ""
        if stock_data:
            context = (
                f"Context — {stock_data.get('symbol', 'N/A')}: "
                f"Price=${stock_data.get('current_price', 'N/A')}, "
                f"P/E={stock_data.get('pe_ratio', 'N/A')}, "
                f"Rec={stock_data.get('recommendation', 'N/A')}\n\n"
            )
        system_prompt = (
            "You are an expert financial advisor. "
            "Provide clear, helpful answers. Always include a disclaimer that this is not personalized financial advice."
        )
        prompt = f"{context}Question: {question}\n\nProvide a helpful, informative answer with a brief disclaimer."
        response = await self.query_with_retry(prompt, system_prompt, temperature=0.5, max_tokens=600, user_id=user_id)
        return response or "I'm unable to answer that question right now. Please try again later."

    async def get_market_sentiment(self, symbols: List[str], news_data: Dict, user_id: str = "anonymous") -> Dict:
        symbols_str = ", ".join(symbols)
        # Truncate news to avoid huge prompts
        truncated_news = {s: [n.get('title', '') for n in v[:3]] for s, v in news_data.items()}
        prompt = (
            f"Analyze market sentiment for: {symbols_str}\n\n"
            f"Recent headlines: {json.dumps(truncated_news, default=str)}\n\n"
            "Return JSON with: overall_sentiment (bullish/bearish/neutral), "
            "sentiment_scores (dict symbol→1-10), market_outlook (string), "
            "key_events (array), trading_opportunities (array)."
        )
        response = await self.query_with_retry(prompt, temperature=0.2, user_id=user_id)
        if response:
            parsed = self._extract_json(response)
            if parsed:
                return parsed
        return {
            "overall_sentiment": "neutral",
            "sentiment_scores": {s: 5 for s in symbols},
            "market_outlook": "Mixed signals in the market",
            "key_events": [],
            "trading_opportunities": []
        }

    def get_rate_limit_stats(self) -> Dict:
        return self.rate_limiter.get_stats()

    # ------------------------------------------------------------------
    # Fallbacks
    # ------------------------------------------------------------------
    def _fallback_comparison(self, stocks_data: List[Dict]) -> Dict:
        valid = [s for s in stocks_data if s.get('symbol')]
        if not valid:
            return {
                "best_for_growth": "N/A", "best_for_value": "N/A",
                "best_for_income": "N/A", "safest_option": "N/A",
                "most_volatile": "N/A", "overall_recommendation": "N/A",
                "analysis": "Unable to analyze stocks at this time.",
                "risk_assessment": "Please try again later.",
                "investment_tips": ["Check back later for AI analysis"]
            }

        def _sg(stock, key, default=0):
            val = stock.get(key, default)
            return val if val is not None else default

        def _rev(s):
            gm = s.get('growth_metrics') or {}
            return gm.get('revenue_growth') or 0

        best_growth = max(valid, key=_rev)
        best_value  = min(valid, key=lambda x: _sg(x, 'pe_ratio', 9999))
        best_income = max(valid, key=lambda x: _sg(x, 'dividend_yield', 0))
        safest      = min(valid, key=lambda x: _sg(x, 'volatility', 9999))
        most_vol    = max(valid, key=lambda x: _sg(x, 'volatility', 0))
        best_all    = max(valid, key=lambda x: _sg(x, 'ai_score', 0))

        return {
            "best_for_growth":        best_growth.get('symbol', 'N/A'),
            "best_for_value":         best_value.get('symbol',  'N/A'),
            "best_for_income":        best_income.get('symbol', 'N/A'),
            "safest_option":          safest.get('symbol',      'N/A'),
            "most_volatile":          most_vol.get('symbol',    'N/A'),
            "overall_recommendation": best_all.get('symbol',    'N/A'),
            "analysis": "Based on fundamental metrics, these stocks show different investment profiles.",
            "risk_assessment": "Consider your risk tolerance and investment horizon before deciding.",
            "investment_tips": [
                f"{best_growth.get('symbol')} shows strongest growth potential",
                f"{best_income.get('symbol')} offers best dividend income",
                f"{safest.get('symbol')} is most suitable for conservative investors"
            ]
        }

    def _fallback_thesis(self, stock_data: Dict) -> Dict:
        symbol = stock_data.get('symbol', 'N/A')
        pe     = stock_data.get('pe_ratio',      0) or 0
        roe    = stock_data.get('roe',            0) or 0
        div    = stock_data.get('dividend_yield', 0) or 0
        debt   = stock_data.get('debt_to_equity', 0) or 0
        rec    = stock_data.get('recommendation', 'Hold')

        strengths = ["Established market position in its sector"]
        if 0 < pe < 20:
            strengths.append("Reasonable valuation relative to peers")
        if roe > 15:
            strengths.append("Strong profitability metrics")
        if div > 2:
            strengths.append("Attractive dividend yield")

        weaknesses = ["Subject to broader market volatility"]
        if pe > 30:
            weaknesses.append("Trading at premium valuation")

        risks = ["Overall market conditions could impact performance"]
        if debt > 1.5:
            risks.append("Higher than ideal leverage levels")
        risks.append("Regulatory and macro-economic uncertainty")

        valuation = "Fairly Valued"
        if 0 < pe < 15:
            valuation = "Undervalued"
        elif pe > 25:
            valuation = "Overvalued"

        return {
            "thesis": f"{symbol} presents a {'compelling' if rec in ['Buy', 'Strong Buy'] else 'cautious'} investment case based on current fundamentals.",
            "strengths": strengths[:3],
            "weaknesses": weaknesses[:2],
            "risks": risks[:3],
            "outlook": "Monitor next quarterly earnings for directional cues",
            "catalyst": "Earnings growth and sector expansion",
            "valuation_opinion": valuation,
            "action": rec
        }


ai_service = OpenRouterAIService()