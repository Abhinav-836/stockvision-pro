# backend/ai_service.py
import os
import re
import json
import logging
import asyncio
import time
from typing import Dict, Optional, List, Any
from datetime import datetime
from collections import defaultdict
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Rate Limiter
# ---------------------------------------------------------------------------

class RateLimiter:
    """
    Sliding-window rate limiter.
    max_requests per time_window per user_id, plus a daily total cap.
    """
    def __init__(self, max_requests: int = 30, time_window: int = 60, daily_limit: int = 500):
        self.max_requests  = max_requests
        self.time_window   = time_window
        self.daily_limit   = daily_limit
        self.requests:      Dict[str, list] = defaultdict(list)
        self.daily_requests: Dict[str, int]  = defaultdict(int)
        self.total_requests = 0

    def can_make_request(self, user_id: str = "default") -> bool:
        now   = time.time()
        today = datetime.now().strftime("%Y-%m-%d")

        # Slide window
        self.requests[user_id] = [t for t in self.requests[user_id] if now - t < self.time_window]

        if len(self.requests[user_id]) >= self.max_requests:
            logger.warning(f"⚠️  Rate limit exceeded for user {user_id}")
            return False

        if self.daily_requests[today] >= self.daily_limit:
            logger.warning(f"⚠️  Daily limit reached ({self.daily_limit})")
            return False

        self.requests[user_id].append(now)
        self.daily_requests[today] += 1
        self.total_requests += 1
        return True

    def get_stats(self) -> Dict:
        today = datetime.now().strftime("%Y-%m-%d")
        return {
            "total_requests":   self.total_requests,
            "daily_requests":   self.daily_requests[today],
            "daily_limit":      self.daily_limit,
            "active_users":     len(self.requests),
        }


# ---------------------------------------------------------------------------
# AI Service
# ---------------------------------------------------------------------------

class OpenRouterAIService:
    """
    Wraps OpenRouter with:
      - DeepSeek R1 as primary model (best reasoning / financial analysis)
      - Llama 3.3 70B as first fallback (free tier)
      - Mistral 7B as second fallback (free tier)
    """

    # Model identifiers -------------------------------------------------------
    PRIMARY_MODEL  = "deepseek/deepseek-r1"          # DeepSeek R1 — best financial reasoning
    FALLBACK_MODELS = [
        "meta-llama/llama-3.3-70b-instruct:free",    # Free Llama 3.3
        "mistralai/mistral-7b-instruct:free",         # Free Mistral 7B
    ]

    # DeepSeek R1 outputs a <think>…</think> block before the answer.
    # We strip it so only the clean answer / JSON is returned to callers.
    _THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)

    def __init__(self):
        self.api_key  = os.getenv("OPENROUTER_API_KEY")
        self.base_url = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")

        # Allow env override, but default to DeepSeek R1
        self.model = os.getenv("OPENROUTER_MODEL", self.PRIMARY_MODEL)

        if not self.api_key:
            logger.warning("⚠️  OPENROUTER_API_KEY not set — AI features will use fallback mode.")
            self.client = None
        else:
            self.client = OpenAI(
                base_url=self.base_url,
                api_key=self.api_key,
                default_headers={
                    "HTTP-Referer": os.getenv("APP_URL", "https://stockvisionpro.vercel.app"),
                    "X-Title": "StockVision Pro",
                },
            )

        # Rate limiter — DeepSeek R1 is a paid model so be a bit more generous
        # than the old free-tier limits, but stay sensible.
        self.rate_limiter = RateLimiter(
            max_requests=25,
            time_window=60,
            daily_limit=800,
        )

        # Simple in-memory response cache
        self.cache: Dict[str, tuple] = {}
        self.cache_ttl = int(os.getenv("CACHE_TTL", 600))  # 10 minutes

        self.user_request_count: Dict[str, int] = defaultdict(int)

        logger.info(f"✅ AI Service ready — primary model: {self.model}")
        logger.info(f"✅ Fallback chain: {' → '.join(self.FALLBACK_MODELS)}")
        logger.info(f"✅ Rate limit: {self.rate_limiter.max_requests} req/min/user, "
                    f"{self.rate_limiter.daily_limit} req/day total")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _strip_think(self, text: str) -> str:
        """Remove DeepSeek R1 chain-of-thought <think>…</think> blocks."""
        return self._THINK_RE.sub("", text).strip()

    def _extract_json(self, text: str) -> Optional[Dict]:
        """
        Robustly pull a JSON object out of a model response.
        Handles markdown fences (```json … ```) and bare objects.
        """
        # 1. Strip think blocks first
        text = self._strip_think(text)

        # 2. Try markdown-fenced JSON
        fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if fence:
            try:
                return json.loads(fence.group(1))
            except json.JSONDecodeError:
                pass

        # 3. Try bare JSON object
        obj = re.search(r"\{.*\}", text, re.DOTALL)
        if obj:
            try:
                return json.loads(obj.group())
            except json.JSONDecodeError:
                pass

        return None

    def _cache_key(self, prompt: str, system_prompt: Optional[str]) -> str:
        sp = (system_prompt or "")[:80]
        return f"{prompt[:120]}|{sp}"

    def _get_cache(self, key: str) -> Optional[str]:
        if key in self.cache:
            ts, val = self.cache[key]
            if (datetime.now() - ts).total_seconds() < self.cache_ttl:
                logger.debug("✅ AI cache hit")
                return val
            del self.cache[key]
        return None

    def _set_cache(self, key: str, value: str):
        self.cache[key] = (datetime.now(), value)

    def _make_completion(self, model: str, messages: list, temperature: float, max_tokens: int) -> Optional[str]:
        """Synchronous completion call (run inside executor)."""
        completion = self.client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            top_p=0.9,
        )
        raw = completion.choices[0].message.content or ""
        return self._strip_think(raw)

    # ------------------------------------------------------------------
    # Core query with model fallback
    # ------------------------------------------------------------------

    async def query(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: int = 1000,
    ) -> Optional[str]:
        """
        Send prompt to the primary model; fall back down the chain on error.
        Returns the cleaned response text or None.
        """
        if not self.client:
            return None

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        # Check cache
        cache_key = self._cache_key(prompt, system_prompt)
        cached = self._get_cache(cache_key)
        if cached:
            return cached

        models_to_try = [self.model] + [m for m in self.FALLBACK_MODELS if m != self.model]

        for model in models_to_try:
            try:
                logger.info(f"🤖 Querying model: {model}")
                response = await asyncio.wait_for(
                    asyncio.get_event_loop().run_in_executor(
                        None,
                        lambda m=model: self._make_completion(m, messages, temperature, max_tokens),
                    ),
                    timeout=30.0,  # R1 can be slow; give it 30 s
                )
                if response:
                    self._set_cache(cache_key, response)
                    logger.info(f"✅ Got response from {model} ({len(response)} chars)")
                    return response
            except asyncio.TimeoutError:
                logger.warning(f"⏱️  Timeout on {model}, trying next…")
            except Exception as e:
                logger.warning(f"❌ {model} error: {e}, trying next…")

        logger.error("All models in fallback chain failed")
        return None

    async def query_with_retry(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: int = 1000,
        response_format: Optional[Dict] = None,
        max_retries: int = 2,
        user_id: str = "anonymous",
    ) -> Optional[str]:
        """Rate-limited wrapper around `query` with exponential back-off."""

        if not self.rate_limiter.can_make_request(user_id):
            logger.warning(f"⚠️  Rate limit hit for user {user_id}")
            return None

        for attempt in range(max_retries):
            response = await self.query(prompt, system_prompt, temperature, max_tokens)
            if response:
                return response
            if attempt < max_retries - 1:
                wait = 2 ** attempt
                logger.info(f"Retry {attempt + 1}/{max_retries} in {wait}s…")
                await asyncio.sleep(wait)

        logger.error(f"All {max_retries} retry attempts failed")
        return None

    # ------------------------------------------------------------------
    # Public AI methods
    # ------------------------------------------------------------------

    async def analyze_stock_comparison(
        self, stocks_data: List[Dict], user_id: str = "anonymous"
    ) -> Dict:
        """
        Generate a structured AI comparison of 2–5 stocks.
        Uses DeepSeek R1 for superior financial reasoning.
        """
        summaries = []
        for s in stocks_data:
            mcap = s.get("market_cap", 0) or 0
            summaries.append(
                f"{s.get('symbol','N/A')} ({s.get('company_name','N/A')}):\n"
                f"  Price=${s.get('current_price',0):.2f}  Chg={s.get('change_percent',0):+.2f}%\n"
                f"  P/E={s.get('pe_ratio','N/A')}  P/B={s.get('pb_ratio','N/A')}\n"
                f"  ROE={s.get('roe','N/A')}%  D/E={s.get('debt_to_equity','N/A')}\n"
                f"  DivYield={s.get('dividend_yield','N/A')}%  MktCap=${mcap/1e9:.2f}B\n"
                f"  AIScore={s.get('ai_score',0)}/100  Rec={s.get('recommendation','N/A')}\n"
                f"  Risk={s.get('risk_level','N/A')}"
            )

        system_prompt = (
            "You are a senior equity research analyst at a top-tier investment bank. "
            "Your job is to produce precise, data-driven stock comparisons. "
            "Respond ONLY with valid JSON — no markdown, no preamble."
        )

        prompt = (
            "Compare the following stocks and return a JSON object with EXACTLY these fields:\n\n"
            + "\n\n".join(summaries)
            + "\n\nRequired JSON fields:\n"
            "- best_for_growth: string (ticker symbol)\n"
            "- best_for_value: string (ticker symbol)\n"
            "- best_for_income: string (ticker symbol, or 'None' if no dividends)\n"
            "- safest_option: string (ticker symbol)\n"
            "- most_volatile: string (ticker symbol)\n"
            "- overall_recommendation: string (ticker symbol)\n"
            "- analysis: string (3–4 sentence comparative summary with specific metric citations)\n"
            "- risk_assessment: string (3–4 sentence risk analysis per stock)\n"
            "- investment_tips: array of exactly 3 strings (one actionable tip per leading stock)\n\n"
            "Return ONLY valid JSON."
        )

        response = await self.query_with_retry(
            prompt, system_prompt, temperature=0.2, max_tokens=1200, user_id=user_id
        )

        if response:
            parsed = self._extract_json(response)
            if parsed:
                return parsed
            logger.warning("Could not parse comparison JSON from AI response")

        logger.info("Using rule-based fallback comparison")
        return self._fallback_comparison(stocks_data)

    async def generate_investment_thesis(
        self, stock_data: Dict, user_id: str = "anonymous"
    ) -> Dict:
        """
        Generate a detailed investment thesis for a single stock.
        DeepSeek R1's reasoning capability shines here.
        NEWS REMOVED for faster response times (8-15s instead of 25-40s)
        """
        symbol  = stock_data.get("symbol", "N/A")
        company = stock_data.get("company_name", "N/A")

        system_prompt = (
            "You are a CFA-certified portfolio manager writing an investment thesis. "
            "Be balanced, cite the specific metrics provided, and give a clear actionable view. "
            "Respond ONLY with valid JSON — no markdown, no preamble."
        )

        prompt = (
            f"Write a concise investment thesis for {symbol} ({company}).\n\n"
            f"Metrics:\n"
            f"  Price=${stock_data.get('current_price','N/A')}\n"
            f"  P/E={stock_data.get('pe_ratio','N/A')}  P/B={stock_data.get('pb_ratio','N/A')}\n"
            f"  ROE={stock_data.get('roe','N/A')}%  D/E={stock_data.get('debt_to_equity','N/A')}\n"
            f"  DivYield={stock_data.get('dividend_yield','N/A')}%\n"
            f"  Volatility={stock_data.get('volatility','N/A')}\n"
            f"  AIScore={stock_data.get('ai_score','N/A')}/100\n"
            f"  Recommendation={stock_data.get('recommendation','N/A')}\n\n"
            "Return a JSON object with these fields:\n"
            "- thesis: string (2–3 sentence investment thesis)\n"
            "- strengths: array of 3 strings\n"
            "- weaknesses: array of 2 strings\n"
            "- risks: array of 3 strings\n"
            "- outlook: string (short-term price/business outlook)\n"
            "- catalyst: string (specific near-term catalyst)\n"
            "- valuation_opinion: string (Undervalued | Fairly Valued | Overvalued)\n"
            "- action: string (Strong Buy | Buy | Hold | Sell | Strong Sell)\n\n"
            "Return ONLY valid JSON."
        )

        response = await self.query_with_retry(
            prompt, system_prompt, temperature=0.3, max_tokens=1000, user_id=user_id
        )

        if response:
            parsed = self._extract_json(response)
            if parsed:
                return parsed
            logger.warning("Could not parse thesis JSON")

        return self._fallback_thesis(stock_data)

    async def answer_question(
        self, question: str, stock_data: Optional[Dict] = None, user_id: str = "anonymous"
    ) -> str:
        """Answer any investment-related question, optionally with stock context."""
        context = ""
        if stock_data:
            context = (
                f"Current data for {stock_data.get('symbol','N/A')}:\n"
                f"  Price=${stock_data.get('current_price','N/A')}\n"
                f"  P/E={stock_data.get('pe_ratio','N/A')}\n"
                f"  ROE={stock_data.get('roe','N/A')}%\n"
                f"  Recommendation={stock_data.get('recommendation','N/A')}\n\n"
            )

        system_prompt = (
            "You are an expert financial educator. Provide clear, accurate answers about "
            "investing and stocks. Always include a brief disclaimer that this is not "
            "personalised financial advice."
        )

        prompt = f"{context}Question: {question}\n\nProvide a helpful, concise answer with a brief disclaimer."

        response = await self.query_with_retry(
            prompt, system_prompt, temperature=0.5, max_tokens=700, user_id=user_id
        )
        return response or "Unable to answer that question right now. Please try again later."

    async def get_market_sentiment(
        self, symbols: List[str], news_data: Dict, user_id: str = "anonymous"
    ) -> Dict:
        """Analyse market sentiment from news headlines."""
        symbols_str = ", ".join(symbols)

        prompt = (
            f"Analyse market sentiment for these stocks: {symbols_str}\n\n"
            f"Recent news:\n{json.dumps(news_data, indent=2, default=str)}\n\n"
            "Return a JSON object with:\n"
            "- overall_sentiment: string (bullish | bearish | neutral)\n"
            "- sentiment_scores: object mapping each symbol to a score 1–10\n"
            "- market_outlook: string (2–3 sentence outlook)\n"
            "- key_events: array of up to 3 significant news items\n"
            "- trading_opportunities: array of up to 3 opportunities\n\n"
            "Return ONLY valid JSON."
        )

        response = await self.query_with_retry(
            prompt, temperature=0.2, max_tokens=800, user_id=user_id
        )

        if response:
            parsed = self._extract_json(response)
            if parsed:
                return parsed

        return {
            "overall_sentiment": "neutral",
            "sentiment_scores": {s: 5 for s in symbols},
            "market_outlook": "Mixed signals — AI sentiment unavailable.",
            "key_events": [],
            "trading_opportunities": [],
        }

    def get_rate_limit_stats(self) -> Dict:
        return self.rate_limiter.get_stats()

    # ------------------------------------------------------------------
    # Rule-based fallbacks
    # ------------------------------------------------------------------

    def _fallback_comparison(self, stocks_data: List[Dict]) -> Dict:
        valid = [s for s in stocks_data if s.get("symbol")]
        if not valid:
            return {
                "best_for_growth": "N/A", "best_for_value": "N/A",
                "best_for_income": "N/A", "safest_option": "N/A",
                "most_volatile": "N/A", "overall_recommendation": "N/A",
                "analysis": "Unable to analyse stocks at this time.",
                "risk_assessment": "Please try again later.",
                "investment_tips": ["Check back later for AI analysis"],
            }

        def sg(stock, key, default=0):
            v = stock.get(key, default)
            return v if (v is not None and v != "N/A") else default

        best_growth   = max(valid, key=lambda x: sg(x.get("growth_metrics", {}), "revenue_growth"))
        best_value    = min(valid, key=lambda x: sg(x, "pe_ratio", float("inf")))
        best_income   = max(valid, key=lambda x: sg(x, "dividend_yield"))
        safest        = min(valid, key=lambda x: sg(x, "volatility", float("inf")))
        most_volatile = max(valid, key=lambda x: sg(x, "volatility"))
        best_overall  = max(valid, key=lambda x: sg(x, "ai_score"))

        return {
            "best_for_growth":        best_growth.get("symbol", "N/A"),
            "best_for_value":         best_value.get("symbol", "N/A"),
            "best_for_income":        best_income.get("symbol", "N/A"),
            "safest_option":          safest.get("symbol", "N/A"),
            "most_volatile":          most_volatile.get("symbol", "N/A"),
            "overall_recommendation": best_overall.get("symbol", "N/A"),
            "analysis": "Based on fundamental metrics, these stocks show different investment profiles.",
            "risk_assessment": "Consider your risk tolerance and investment horizon before deciding.",
            "investment_tips": [
                f"{best_growth.get('symbol')} shows strongest growth potential",
                f"{best_income.get('symbol')} offers best dividend income",
                f"{safest.get('symbol')} is most suitable for conservative investors",
            ],
        }

    def _fallback_thesis(self, stock_data: Dict) -> Dict:
        symbol = stock_data.get("symbol", "N/A")
        pe     = stock_data.get("pe_ratio")  or 0
        roe    = stock_data.get("roe")        or 0
        div    = stock_data.get("dividend_yield") or 0
        rec    = stock_data.get("recommendation", "Hold")

        strengths = ["Strong market position in its sector"]
        if pe and pe < 20:    strengths.append("Reasonable valuation vs peers")
        if roe and roe > 15:  strengths.append("Strong profitability metrics")
        if div and div > 2:   strengths.append("Attractive dividend yield")

        weaknesses = ["Subject to broader market volatility"]
        if pe and pe > 30:    weaknesses.append("Premium valuation limits upside")

        risks = ["Overall market conditions could impact performance"]
        if (stock_data.get("debt_to_equity") or 0) > 1.5:
            risks.append("Elevated leverage increases downside risk")

        if pe and pe < 15:       valuation = "Undervalued"
        elif pe and pe > 25:     valuation = "Overvalued"
        else:                    valuation = "Fairly Valued"

        return {
            "thesis": (
                f"{symbol} presents a {'compelling' if rec in ('Buy','Strong Buy') else 'cautious'} "
                "investment case based on current fundamentals."
            ),
            "strengths":          strengths[:3],
            "weaknesses":         weaknesses[:2],
            "risks":              risks[:3],
            "outlook":            "Monitor next quarterly earnings for direction",
            "catalyst":           "Earnings growth and operational leverage",
            "valuation_opinion":  valuation,
            "action":             rec,
        }


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

ai_service = OpenRouterAIService()