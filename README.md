# StockVision Pro 📈
### AI-Powered Market Intelligence Platform
StockVision Pro bridges the gap between raw market data and actionable investment intelligence by combining institutional-grade financial analytics with cutting-edge AI reasoning.

## ✨ Key Features

### 📊 Real-Time Market Intelligence
- **Live Price Streaming**: WebSocket-based real-time updates for NSE, BSE, and US markets
- **Multi-Stock Comparison**: Side-by-side fundamental and technical analysis for 2-5 stocks
- **Market Indices**: Real-time tracking of S&P 500, NASDAQ, Dow Jones, VIX, and commodities
- **Intelligent Caching**: LRU cache with TTL for sub-50ms response times

### 🤖 AI-Powered Analysis
- **DeepSeek R1 Integration**: Primary model for complex financial reasoning and comparative analysis
- **Fallback Chain**: Automatic fallback to Llama 3.3 70B and Mistral 7B for high availability
- **Investment Thesis Generation**: Structured analysis with strengths, weaknesses, risks, and catalysts
- **Market Sentiment Analysis**: News-driven sentiment scoring with actionable insights
- **Natural Language Q&A**: Ask investment questions with optional stock-specific grounding

### 📈 Technical Analytics
- **Indicators**: RSI, MACD, SMA (20/50/200), Bollinger Bands
- **Volatility Metrics**: Annualized volatility calculation from historical data
- **Trend Detection**: Automated bull/bear trend classification

### 💰 Fundamental Analysis
- **Valuation Metrics**: P/E, P/B, EV/EBITDA with sector-aware scoring
- **Profitability**: ROE, ROA, EPS with intelligent percentage normalization
- **Financial Health**: Debt-to-Equity, Current Ratio, Interest Coverage
- **Growth Metrics**: Revenue growth, earnings growth, quarterly momentum

### 🎯 AI Scoring Engine
- **0-100 Score**: Multi-factor weighted scoring system
- **Sector-Aware Valuation**: Relaxed P/B scoring for technology stocks
- **Dividend Trap Detection**: Penalizes unsustainably high yields (>6%)
- **Risk Assessment**: Combined volatility + leverage scoring

### 🔄 Real-Time Updates
- **WebSocket Subscriptions**: Live price updates every 5 seconds
- **Market Index Streaming**: 60-second automatic updates
- **Cache Invalidation**: Manual and automatic cache management

## 🏗 System Architecture
┌─────────────────────────────────────────────────────────────┐
│ Client Applications │
│ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ │
│ │ Web │ │ Mobile │ │ API │ │ WebSocket│ │
│ └─────┬────┘ └─────┬────┘ └─────┬────┘ └─────┬────┘ │
└────────┼─────────────┼─────────────┼─────────────┼──────────┘
│ │ │ │
▼ ▼ ▼ ▼
┌─────────────────────────────────────────────────────────────┐
│ FastAPI Gateway Layer │
│ ┌──────────────────────────────────────────────────────┐ │
│ │ CORS │ Rate Limiting │ Request Validation │ Logging │ │
│ └──────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
│ │
▼ ▼
┌──────────────────┐ ┌─────────────────────────┐
│ Cache Layer │ │ AI Service Layer │
│ ┌────────────┐ │ │ ┌──────────────────┐ │
│ │ LRU Cache │ │ │ │ DeepSeek R1 │ │
│ │ (1000 cap) │ │ │ │ (Primary) │ │
│ └────────────┘ │ │ └────────┬─────────┘ │
│ │ │ ▼ │
└──────────────────┘ │ ┌──────────────────┐ │
│ │ │ Llama 3.3 70B │ │
▼ │ │ (Fallback 1) │ │
┌──────────────────┐ │ └────────┬─────────┘ │
│ Data Layer │ │ ▼ │
│ ┌────────────┐ │ │ ┌──────────────────┐ │
│ │ yFinance │ │ │ │ Mistral 7B │ │
│ │ (NSE/BSE) │ │ │ │ (Fallback 2) │ │
│ └────────────┘ │ │ └──────────────────┘ │
└──────────────────┘ └─────────────────────────┘

text

## 🛠 Technology Stack

### Backend
| Component | Technology | Version |
|-----------|------------|---------|
| Framework | FastAPI | 0.115.0+ |
| Server | Uvicorn | 0.30.0+ |
| Data Processing | Pandas/NumPy | 2.0+/1.24+ |
| Market Data | yFinance | 0.2.0+ |
| Async Tasks | asyncio | Built-in |

### AI & ML
| Component | Technology | Purpose |
|-----------|------------|---------|
| Primary Model | DeepSeek R1 | Complex financial reasoning |
| Fallback 1 | Llama 3.3 70B | High availability |
| Fallback 2 | Mistral 7B | Last resort |
| API Gateway | OpenRouter | Unified AI access |
| Rate Limiting | Custom sliding window | 25 req/min/user |

### Caching & Performance
- **In-Memory Cache**: LRU with 60s-600s TTL
- **Response Time**: <50ms for cached, <500ms for fresh data
- **Concurrent Requests**: Async/await pattern with 30s timeouts

## 📦 Installation

### Prerequisites
Python 3.11+
pip (latest)
Git

Development Guidelines
Follow PEP 8 style guide

Add type hints for all functions

Write docstrings for public methods

Include unit tests for new features

Update documentation for API changes

📄 License
Distributed under the MIT License. See LICENSE for more information.

⚠️ Disclaimer
StockVision Pro is an educational and professional tool for informational purposes only.

All AI-generated recommendations are based on historical data and statistical models

Past performance does not guarantee future results

Investing in stock markets involves significant risk of loss

Always consult with a certified financial advisor before making investment decisions

The developers assume no liability for financial losses incurred using this platform
