# backend/ai_service.py
import os
import json
import logging
import asyncio
import time
from typing import Dict, Optional, List, Any
from datetime import datetime, timedelta
from collections import defaultdict
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

class RateLimiter:
    def __init__(self, max_requests=30, time_window=60):
        """
        Rate limiter to prevent API key overuse
        max_requests: maximum requests per time_window
        time_window: time window in seconds
        """
        self.max_requests = max_requests
        self.time_window = time_window
        self.requests = defaultdict(list)
        self.total_requests = 0
        self.daily_requests = defaultdict(int)
        self.daily_limit = 500  # Conservative daily limit

    def can_make_request(self, user_id="default"):
        """
        Check if request can be made based on rate limits
        Returns: bool
        """
        now = time.time()
        
        # Clean old requests for this user
        self.requests[user_id] = [req_time for req_time in self.requests[user_id] 
                                  if now - req_time < self.time_window]
        
        # Check user rate limit
        if len(self.requests[user_id]) >= self.max_requests:
            logger.warning(f"⚠️ Rate limit exceeded for user {user_id}")
            return False
        
        # Check daily total limit (across all users)
        today = datetime.now().strftime("%Y-%m-%d")
        if self.daily_requests[today] >= self.daily_limit:
            logger.warning(f"⚠️ Daily limit reached: {self.daily_limit}")
            return False
        
        # Allow request
        self.requests[user_id].append(now)
        self.daily_requests[today] += 1
        self.total_requests += 1
        
        return True

    def get_stats(self):
        """Get rate limiter statistics"""
        today = datetime.now().strftime("%Y-%m-%d")
        return {
            "total_requests": self.total_requests,
            "daily_requests": self.daily_requests[today],
            "daily_limit": self.daily_limit,
            "active_users": len(self.requests)
        }

class OpenRouterAIService:
    def __init__(self):
        self.api_key = os.getenv("OPENROUTER_API_KEY")
        self.base_url = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
        self.model = os.getenv("OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct:free")
        
        # Free tier models as fallbacks
        self.free_models = [
            "meta-llama/llama-3.3-70b-instruct:free",
            "google/gemma-7b-it:free",
            "mistralai/mistral-7b-instruct:free"
        ]
        
        if not self.api_key:
            logger.warning("⚠️ OPENROUTER_API_KEY not set. AI features will use fallback mode.")
            self.client = None
        else:
            self.client = OpenAI(
                base_url=self.base_url,
                api_key=self.api_key,
                default_headers={
                    "HTTP-Referer": "http://localhost:5173",
                    "X-Title": "AI Stock Advisor"
                }
            )
        
        # Initialize rate limiter - conservative limits for free tier
        self.rate_limiter = RateLimiter(
            max_requests=20,  # Max 20 requests per minute per user
            time_window=60
        )
        
        self.cache = {}
        self.cache_ttl = int(os.getenv("CACHE_TTL", 600))  # Increased cache time to 10 minutes
        self.user_request_count = defaultdict(int)
        
        logger.info(f"✅ OpenRouter AI Service initialized with model: {self.model}")
        logger.info(f"✅ Rate limiting: 20 requests/minute/user, {self.rate_limiter.daily_limit} requests/day total")

    async def query_with_retry(self, 
                              prompt: str, 
                              system_prompt: Optional[str] = None,
                              temperature: float = 0.3,
                              max_tokens: int = 800,
                              response_format: Optional[Dict] = None,
                              max_retries: int = 2,
                              user_id: str = "anonymous") -> Optional[str]:
        """
        Send a prompt to OpenRouter with retry logic and rate limiting
        """
        
        # Check rate limit first
        if not self.rate_limiter.can_make_request(user_id):
            logger.warning(f"⚠️ Rate limit hit for user {user_id}")
            return None
        
        for attempt in range(max_retries):
            try:
                response = await self.query(prompt, system_prompt, temperature, max_tokens, response_format)
                if response:
                    return response
            except Exception as e:
                logger.warning(f"AI query attempt {attempt + 1} failed: {e}")
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt
                    logger.info(f"Retrying in {wait_time} seconds...")
                    await asyncio.sleep(wait_time)
        
        logger.error(f"All {max_retries} attempts failed")
        return None

    async def query(self, 
                   prompt: str, 
                   system_prompt: Optional[str] = None,
                   temperature: float = 0.3,
                   max_tokens: int = 800,
                   response_format: Optional[Dict] = None) -> Optional[str]:
        """Send a prompt to OpenRouter and get response"""
        
        # If no API key, return None (will use fallback)
        if not self.client:
            logger.debug("No API key available, skipping AI query")
            return None

        try:
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})

            # Check cache
            cache_key = f"{prompt[:100]}_{system_prompt[:100] if system_prompt else ''}"
            if cache_key in self.cache:
                cache_time, cache_response = self.cache[cache_key]
                if (datetime.now() - cache_time).seconds < self.cache_ttl:
                    logger.debug("✅ AI response cache hit")
                    return cache_response

            # Make API call with timeout
            try:
                completion = await asyncio.wait_for(
                    asyncio.get_event_loop().run_in_executor(
                        None,
                        lambda: self.client.chat.completions.create(
                            model=self.model,
                            messages=messages,
                            temperature=temperature,
                            max_tokens=max_tokens,
                            top_p=0.7,
                            frequency_penalty=0,
                            presence_penalty=0
                        )
                    ),
                    timeout=15.0
                )

                response = completion.choices[0].message.content
                
                # Cache the response
                self.cache[cache_key] = (datetime.now(), response)
                
                return response

            except asyncio.TimeoutError:
                logger.error("❌ OpenRouter API timeout")
                return None

        except Exception as e:
            logger.error(f"❌ OpenRouter API error: {e}")
            return None

    async def analyze_stock_comparison(self, stocks_data: List[Dict], user_id: str = "anonymous") -> Dict:
        """
        Generate AI analysis comparing multiple stocks
        Returns structured comparison data
        """
        # Prepare stock data summary
        stocks_summary = []
        for stock in stocks_data:
            symbol = stock.get('symbol', 'N/A')
            company = stock.get('company_name', 'N/A')
            price = stock.get('current_price', 0)
            change = stock.get('change_percent', 0)
            pe = stock.get('pe_ratio', 'N/A')
            pb = stock.get('pb_ratio', 'N/A')
            roe = stock.get('roe', 'N/A')
            debt = stock.get('debt_to_equity', 'N/A')
            div = stock.get('dividend_yield', 'N/A')
            mcap = stock.get('market_cap', 0)
            ai_score = stock.get('ai_score', 0)
            rec = stock.get('recommendation', 'N/A')
            risk = stock.get('risk_level', 'N/A')
            
            summary = f"""
{symbol} ({company}):
- Current Price: ${price:.2f}
- Change: {change:+.2f}%
- P/E Ratio: {pe}
- P/B Ratio: {pb}
- ROE: {roe}%
- Debt/Equity: {debt}
- Dividend Yield: {div}%
- Market Cap: ${mcap/1e9:.2f}B
- AI Score: {ai_score}/100
- Recommendation: {rec}
- Risk Level: {risk}
"""
            stocks_summary.append(summary)

        system_prompt = """You are a professional financial analyst with expertise in stock market analysis. 
Provide a detailed, objective comparison of the given stocks based on fundamental metrics.
Always respond with valid JSON format only, no additional text."""

        prompt = f"""Analyze these stocks and provide a comprehensive comparison:

{''.join(stocks_summary)}

Return a JSON object with EXACTLY these fields:
- best_for_growth: string (symbol of stock best for growth investors)
- best_for_value: string (symbol of stock best for value investors)  
- best_for_income: string (symbol of stock best for dividend income)
- safest_option: string (symbol with lowest risk)
- most_volatile: string (symbol with highest volatility)
- overall_recommendation: string (symbol of most recommended stock)
- analysis: string (2-3 sentence summary of comparison)
- risk_assessment: string (2-3 sentence risk analysis)
- investment_tips: array of 3 strings (specific tips for each stock)

Return ONLY valid JSON, no other text."""

        # Try AI query first, fallback to rule-based if rate limited or fails
        response = await self.query_with_retry(prompt, system_prompt, temperature=0.2, user_id=user_id)
        
        if response:
            try:
                # Extract JSON from response
                import re
                json_match = re.search(r'\{.*\}', response, re.DOTALL)
                if json_match:
                    return json.loads(json_match.group())
            except json.JSONDecodeError:
                logger.warning("Could not parse JSON from AI response")
        
        # Fallback to rule-based comparison
        logger.info("Using fallback comparison (AI unavailable or rate limited)")
        return self._fallback_comparison(stocks_data)

    async def generate_investment_thesis(self, stock_data: Dict, news: List[Dict], user_id: str = "anonymous") -> Dict:
        """
        Generate detailed investment thesis for a single stock
        """
        # Format news headlines
        news_summary = "\n".join([f"- {item.get('title', '')}" for item in news[:5]])
        
        system_prompt = """You are a professional financial analyst writing an investment thesis.
Provide a balanced, insightful analysis based on fundamentals and recent news.
Return ONLY valid JSON, no other text."""

        symbol = stock_data.get('symbol', 'N/A')
        company = stock_data.get('company_name', 'N/A')
        price = stock_data.get('current_price', 'N/A')
        pe = stock_data.get('pe_ratio', 'N/A')
        pb = stock_data.get('pb_ratio', 'N/A')
        roe = stock_data.get('roe', 'N/A')
        debt = stock_data.get('debt_to_equity', 'N/A')
        div = stock_data.get('dividend_yield', 'N/A')
        vol = stock_data.get('volatility', 'N/A')
        score = stock_data.get('ai_score', 'N/A')
        rec = stock_data.get('recommendation', 'N/A')

        prompt = f"""Create a detailed investment thesis for {symbol} ({company}):

**Key Metrics:**
- Current Price: ${price}
- P/E Ratio: {pe}
- P/B Ratio: {pb}
- ROE: {roe}%
- Debt/Equity: {debt}
- Dividend Yield: {div}%
- Volatility: {vol}
- AI Score: {score}/100
- Recommendation: {rec}

**Recent News:**
{news_summary}

**Return a JSON with:**
- thesis: string (2-3 sentence investment thesis)
- strengths: array of 3 strings (key strengths)
- weaknesses: array of 2 strings (key weaknesses)
- risks: array of 3 strings (primary risks)
- outlook: string (short-term outlook)
- catalyst: string (potential catalyst for growth)
- valuation_opinion: string (undervalued, fairly valued, or overvalued)
- action: string (Buy, Hold, or Sell recommendation)

Return ONLY valid JSON."""

        response = await self.query_with_retry(prompt, system_prompt, temperature=0.3, user_id=user_id)
        
        if response:
            try:
                import re
                json_match = re.search(r'\{.*\}', response, re.DOTALL)
                if json_match:
                    return json.loads(json_match.group())
            except json.JSONDecodeError:
                logger.warning("Could not parse thesis JSON")
        
        return self._fallback_thesis(stock_data)

    async def answer_question(self, question: str, stock_data: Optional[Dict] = None, user_id: str = "anonymous") -> str:
        """
        Answer any investment-related question
        """
        context = ""
        if stock_data:
            context = f"""
Current stock data for {stock_data.get('symbol', 'N/A')}:
- Price: ${stock_data.get('current_price', 'N/A')}
- P/E: {stock_data.get('pe_ratio', 'N/A')}
- ROE: {stock_data.get('roe', 'N/A')}%
- Recommendation: {stock_data.get('recommendation', 'N/A')}
"""

        system_prompt = """You are an expert financial advisor assistant. 
Provide clear, accurate, and helpful answers about investing and stocks.
Always include a disclaimer that this is not personalized financial advice."""

        prompt = f"""{context}

Question: {question}

Provide a helpful, informative answer. Include a brief disclaimer."""

        response = await self.query_with_retry(prompt, system_prompt, temperature=0.5, max_tokens=600, user_id=user_id)
        return response or "I'm unable to answer that question right now. Please try again later."

    async def get_market_sentiment(self, symbols: List[str], news_data: Dict, user_id: str = "anonymous") -> Dict:
        """
        Analyze market sentiment based on news and data
        """
        symbols_str = ", ".join(symbols)
        
        prompt = f"""Analyze market sentiment for these stocks: {symbols_str}

Recent news headlines by symbol:
{json.dumps(news_data, indent=2, default=str)}

Return a JSON with:
- overall_sentiment: string (bullish, bearish, or neutral)
- sentiment_scores: dict mapping symbols to sentiment scores (1-10)
- market_outlook: string (brief outlook)
- key_events: array of significant news events
- trading_opportunities: array of potential opportunities

Return ONLY valid JSON."""

        response = await self.query_with_retry(prompt, temperature=0.2, user_id=user_id)
        
        if response:
            try:
                import re
                json_match = re.search(r'\{.*\}', response, re.DOTALL)
                if json_match:
                    return json.loads(json_match.group())
            except:
                pass
        
        return {
            "overall_sentiment": "neutral", 
            "sentiment_scores": {s: 5 for s in symbols},
            "market_outlook": "Mixed signals in the market",
            "key_events": [],
            "trading_opportunities": []
        }

    def get_rate_limit_stats(self):
        """Get current rate limiter statistics"""
        return self.rate_limiter.get_stats()

    def _fallback_comparison(self, stocks_data: List[Dict]) -> Dict:
        """Rule-based fallback when AI fails"""
        valid_stocks = [s for s in stocks_data if s.get('symbol')]
        
        if not valid_stocks:
            return {
                "best_for_growth": "N/A",
                "best_for_value": "N/A",
                "best_for_income": "N/A",
                "safest_option": "N/A",
                "most_volatile": "N/A",
                "overall_recommendation": "N/A",
                "analysis": "Unable to analyze stocks at this time.",
                "risk_assessment": "Please try again later.",
                "investment_tips": ["Check back later for AI analysis"]
            }
        
        # Safe extraction functions
        def safe_get(stock, key, default=0):
            val = stock.get(key, default)
            return val if val is not None and val != 'N/A' else default
        
        def safe_get_growth(stock):
            growth = stock.get('growth_metrics', {})
            return safe_get(growth, 'revenue_growth', 0)
        
        # Find best in each category
        best_growth = max(valid_stocks, key=lambda x: safe_get_growth(x))
        best_value = min(valid_stocks, key=lambda x: safe_get(x, 'pe_ratio', float('inf')))
        best_income = max(valid_stocks, key=lambda x: safe_get(x, 'dividend_yield', 0))
        safest = min(valid_stocks, key=lambda x: safe_get(x, 'volatility', float('inf')))
        most_volatile = max(valid_stocks, key=lambda x: safe_get(x, 'volatility', 0))
        best_overall = max(valid_stocks, key=lambda x: safe_get(x, 'ai_score', 0))
        
        return {
            "best_for_growth": best_growth.get('symbol', 'N/A'),
            "best_for_value": best_value.get('symbol', 'N/A'),
            "best_for_income": best_income.get('symbol', 'N/A'),
            "safest_option": safest.get('symbol', 'N/A'),
            "most_volatile": most_volatile.get('symbol', 'N/A'),
            "overall_recommendation": best_overall.get('symbol', 'N/A'),
            "analysis": "Based on fundamental metrics, these stocks show different investment profiles.",
            "risk_assessment": "Consider your risk tolerance and investment horizon before deciding.",
            "investment_tips": [
                f"{best_growth.get('symbol')} shows strongest growth potential",
                f"{best_income.get('symbol')} offers best dividend income",
                f"{safest.get('symbol')} is most suitable for conservative investors"
            ]
        }

    def _fallback_thesis(self, stock_data: Dict) -> Dict:
        """Rule-based fallback thesis"""
        symbol = stock_data.get('symbol', 'N/A')
        pe = stock_data.get('pe_ratio', 0)
        roe = stock_data.get('roe', 0)
        div = stock_data.get('dividend_yield', 0)
        rec = stock_data.get('recommendation', 'Hold')
        
        strengths = ["Strong market position in its sector"]
        if pe and pe < 20:
            strengths.append("Reasonable valuation compared to peers")
        if roe and roe > 15:
            strengths.append("Strong profitability metrics")
        if div and div > 2:
            strengths.append("Attractive dividend yield")
        
        weaknesses = ["Subject to market volatility"]
        if pe and pe > 30:
            weaknesses.append("Trading at premium valuation")
        
        risks = ["Overall market conditions could impact performance"]
        if stock_data.get('debt_to_equity', 0) > 1.5:
            risks.append("Higher than ideal debt levels")
        
        # Determine valuation
        if pe and pe < 15:
            valuation = "Undervalued"
        elif pe and pe > 25:
            valuation = "Overvalued"
        else:
            valuation = "Fairly Valued"
        
        return {
            "thesis": f"{symbol} presents a {'compelling' if rec in ['Buy', 'Strong Buy'] else 'cautious'} investment case based on current fundamentals.",
            "strengths": strengths[:3],
            "weaknesses": weaknesses[:2],
            "risks": risks[:3],
            "outlook": "Monitor next quarterly earnings for direction",
            "catalyst": "Earnings growth and market expansion",
            "valuation_opinion": valuation,
            "action": rec
        }

# Create singleton instance
ai_service = OpenRouterAIService()