// frontend/src/components/StockForm.jsx (FIXED VERSION)

import React, { useState, useEffect } from 'react';
import { getStockAnalysis, getStockChartData } from '../api';
import StockChart from './StockChart';
import useRealtimePrice from '../hooks/useRealtimePrice';

function StockForm({ onAddToWatchlist, watchlist = [] }) {
  const [symbol, setSymbol] = useState('');
  const [loading, setLoading] = useState(false);
  const [chartLoading, setChartLoading] = useState(false);
  const [stockData, setStockData] = useState(null);
  const [error, setError] = useState('');
  const [chartData, setChartData] = useState([]);
  const [chartPeriod, setChartPeriod] = useState('1mo');

  // FIXED: for Indian stocks the backend returns symbol: "RELIANCE" (the
  // display name, suffix stripped) and original_symbol: "RELIANCE.NS".
  // Every data call below used `symbol`, so after a RELIANCE.NS lookup:
  //  - the WebSocket subscribed to "RELIANCE" (a non-existent US ticker),
  //    so Indian stocks never got a live price;
  //  - the REST polling fallback fetched /api/stock/RELIANCE and replaced
  //    the real ₹ price with the hardcoded $100 demo price;
  //  - changing the chart period re-fetched the chart for "RELIANCE" and
  //    drew a synthetic chart;
  //  - "Add to watchlist" saved "RELIANCE", which analyzed the wrong stock.
  // dataSymbol is the exchange-qualified symbol for all of those.
  const dataSymbol = stockData ? (stockData.original_symbol || stockData.symbol) : null;

  const { price: realtimePrice, change: realtimeChange, connected } = useRealtimePrice(
    dataSymbol,
    stockData?.current_price,
    stockData?.change_percent
  );

  useEffect(() => {
    const handleAnalyzeStock = (e) => {
      setSymbol(e.detail);
      handleSearch(e.detail);
    };
    window.addEventListener('analyzeStock', handleAnalyzeStock);
    return () => window.removeEventListener('analyzeStock', handleAnalyzeStock);
  }, []);

  const handleSearch = async (searchSymbol) => {
    const cleanSymbol = searchSymbol.trim().toUpperCase();
    if (!cleanSymbol) {
      setError('Please enter a stock symbol');
      return;
    }

    setLoading(true);
    setError('');
    setStockData(null);
    setChartData([]);

    // OPTIMIZED: analysis and chart data are independent requests, so
    // fetch them in parallel instead of awaiting the analysis first —
    // the chart used to sit idle for the whole analysis round-trip
    // before it even started loading.
    const chartPromise = fetchChartData(cleanSymbol, chartPeriod);

    try {
      const data = await getStockAnalysis(cleanSymbol);
      console.log('📊 API Response:', data);
      setStockData(data);
    } catch (err) {
      console.error('❌ API Error:', err);
      setError(err.message || 'Failed to fetch stock data');
    } finally {
      setLoading(false);
    }

    await chartPromise;
  };

  const fetchChartData = async (symbolToFetch, period) => {
    if (!symbolToFetch) return;
    
    setChartLoading(true);
    try {
      const chart = await getStockChartData(symbolToFetch, period);
      setChartData(chart);
    } catch (error) {
      console.error('Error fetching chart data:', error);
    } finally {
      setChartLoading(false);
    }
  };

  const handlePeriodChange = async (period) => {
    setChartPeriod(period);
    if (dataSymbol) {
      await fetchChartData(dataSymbol, period);
    }
  };

  const handleSubmit = (e) => {
    e.preventDefault();
    handleSearch(symbol);
  };

  const periods = [
    { value: '1d', label: '1D' },
    { value: '5d', label: '5D' },
    { value: '1mo', label: '1M' },
    { value: '3mo', label: '3M' },
    { value: '6mo', label: '6M' },
    { value: '1y', label: '1Y' },
  ];

  const popularSymbols = ['AAPL', 'MSFT', 'GOOGL', 'TSLA', 'NVDA', 'RELIANCE.NS'];

  // FIXED: every price was hardcoded with "$", so Indian stocks (priced
  // in rupees by NSE/yFinance) were displayed as dollars.
  const currency = stockData?.is_indian_stock ? '₹' : '$';

  const isNum = (v) => typeof v === 'number' && isFinite(v);

  // FIXED: Safer formatLargeNumber function
  const formatLargeNumber = (num) => {
    if (num === null || num === undefined) return 'N/A';
    const parsedNum = typeof num === 'number' ? num : parseFloat(num);
    if (isNaN(parsedNum) || parsedNum === 0) return 'N/A';
    if (parsedNum >= 1e12) return `${currency}${(parsedNum / 1e12).toFixed(2)}T`;
    if (parsedNum >= 1e9) return `${currency}${(parsedNum / 1e9).toFixed(2)}B`;
    if (parsedNum >= 1e6) return `${currency}${(parsedNum / 1e6).toFixed(2)}M`;
    return `${currency}${parsedNum.toFixed(0)}`;
  };

  // FIXED: the metric cards used `value?.toFixed(2) || 'N/A'` and
  // `value ? ... : 'N/A'`, which hid real zeros and showed an unknown
  // dividend yield as a confident "0%". Unknown is now always "N/A" and a
  // real 0 is shown as 0.
  const fmt = (v, { prefix = '', suffix = '', digits = 2 } = {}) =>
    isNum(v) ? `${prefix}${v.toFixed(digits)}${suffix}` : 'N/A';

  // FIXED: helper that decides whether a growth value is actually
  // renderable. The old `&&` guard rendered the row whenever the value
  // was truthy — but "" (empty string) is falsy, 0 is falsy, and null/
  // undefined are falsy too. That guard was ALSO hiding a real 0% value.
  // The new guard keeps a real 0% visible, hides null/undefined/empty-
  // string/NaN, and forces the value through Number() + toFixed(1) so a
  // stray string like "29.7" or "29.7000001" renders cleanly.
  const isRenderableGrowth = (val) => {
    if (val === null || val === undefined) return false;
    if (val === '') return false;
    const n = Number(val);
    return !isNaN(n) && isFinite(n);
  };

  const formatGrowth = (val) => {
    return Number(val).toFixed(1);
  };

  const isInWatchlist = Boolean(dataSymbol) && watchlist.includes(dataSymbol.toUpperCase());

  const displayData = stockData ? {
    ...stockData,
    current_price: realtimePrice ?? stockData.current_price,
    change_percent: realtimeChange ?? stockData.change_percent
  } : null;

  return (
    <div className="stock-analysis">
      {/* Search Section */}
      <div className="search-section glass-card">
        <form onSubmit={handleSubmit} className="search-form">
          <div className="search-wrapper">
            <i className="fas fa-search search-icon"></i>
            <input
              type="text"
              value={symbol}
              onChange={(e) => setSymbol(e.target.value.toUpperCase())}
              placeholder="Enter symbol (e.g., AAPL, RELIANCE.NS)"
              disabled={loading}
              className="search-input"
            />
            {symbol && (
              <button type="button" className="clear-btn" onClick={() => setSymbol('')}>
                <i className="fas fa-times"></i>
              </button>
            )}
          </div>
          <button type="submit" disabled={loading} className="analyze-btn">
            {loading ? (
              <>
                <i className="fas fa-spinner fa-spin"></i>
                <span>Analyzing...</span>
              </>
            ) : (
              <>
                <i className="fas fa-bolt"></i>
                <span>Analyze</span>
              </>
            )}
          </button>
        </form>

        <div className="popular-symbols">
          <span className="label">Popular:</span>
          <div className="symbol-tags">
            {popularSymbols.map(testSymbol => (
              <button
                key={testSymbol}
                onClick={() => { setSymbol(testSymbol); handleSearch(testSymbol); }}
                disabled={loading}
                className="symbol-tag"
              >
                {testSymbol.replace('.NS', '')}
              </button>
            ))}
          </div>
        </div>

        {error && (
          <div className="error-message">
            <i className="fas fa-exclamation-circle"></i>
            <span>{error}</span>
          </div>
        )}
      </div>

      {/* Results */}
      {displayData && (
        <div className="results-container">
          {/* Connection Status */}
          {!connected && (
            <div className="connection-warning">
              <i className="fas fa-plug"></i>
              <span>Using cached data - WebSocket disconnected</span>
            </div>
          )}

          {displayData.is_stale && (
            <div className="connection-warning">
              <i className="fas fa-clock"></i>
              <span>Live data temporarily unavailable — showing last known real price</span>
            </div>
          )}

          {displayData.is_fallback_data && (
            <div className="connection-warning">
              <i className="fas fa-exclamation-triangle"></i>
              <span>{displayData.message || 'Using estimated data — live data temporarily unavailable'}</span>
            </div>
          )}

          {/* Stock Header */}
          <div className="stock-header glass-card">
            <div className="header-left">
              <div className="symbol-wrapper">
                <h1 className="stock-symbol">{displayData.symbol}</h1>
                <button
                  onClick={() => onAddToWatchlist(dataSymbol)}
                  className={`watchlist-btn ${isInWatchlist ? 'active' : ''}`}
                >
                  <i className={`fas fa-star${isInWatchlist ? '' : '-regular'}`}></i>
                </button>
              </div>
              <div className="company-info">
                <h2 className="company-name">{displayData.company_name || displayData.symbol}</h2>
                <div className="stock-tags">
                  {displayData.exchange && (
                    <span className="tag exchange">
                      <i className="fas fa-building"></i>
                      {displayData.exchange}
                    </span>
                  )}
                  {displayData.sector && (
                    <span className="tag sector">
                      <i className="fas fa-tag"></i>
                      {displayData.sector}
                    </span>
                  )}
                  {displayData.is_indian_stock && (
                    <span className="tag indian">
                      <i className="fas fa-flag"></i>
                      NSE/BSE
                    </span>
                  )}
                </div>
              </div>
            </div>
            <div className="header-right">
              <div className="price-wrapper">
                <span className="current-price">{fmt(displayData.current_price, { prefix: currency })}</span>
                <div className={`price-change ${displayData.change_percent >= 0 ? 'positive' : 'negative'}`}>
                  <i className={`fas fa-${displayData.change_percent >= 0 ? 'caret-up' : 'caret-down'}`}></i>
                  <span>{displayData.change_percent >= 0 ? '+' : ''}{displayData.change_percent?.toFixed(2)}%</span>
                </div>
              </div>
              <div className="volume-info">
                <i className="fas fa-chart-bar"></i>
                <span>Vol: {displayData.volume ? (displayData.volume / 1e6).toFixed(2) : 'N/A'}M</span>
              </div>
            </div>
          </div>

          {/* Chart Section */}
          <div className="chart-section glass-card">
            <div className="chart-header">
              <div className="chart-title">
                <i className="fas fa-chart-line"></i>
                <h3>Price History</h3>
              </div>
              <div className="period-selector">
                {periods.map(p => (
                  <button
                    key={p.value}
                    className={`period-btn ${chartPeriod === p.value ? 'active' : ''}`}
                    onClick={() => handlePeriodChange(p.value)}
                    disabled={chartLoading}
                  >
                    {p.label}
                  </button>
                ))}
              </div>
            </div>
            <StockChart
              history={chartData}
              symbol={displayData.symbol}
              currentPrice={displayData.current_price}
              currency={currency}
              isLoading={chartLoading}
            />
          </div>

          {/* AI Insights */}
          <div className="ai-insights glass-card">
            <div className="insights-header">
              <div className="insights-title">
                <i className="fas fa-brain"></i>
                <h3>AI Intelligence</h3>
              </div>
              <span className="confidence-badge">
                <i className="fas fa-shield-alt"></i>
                Confidence: {displayData.confidence || 'N/A'}
              </span>
            </div>

            <div className="insights-grid">
              <div className="insight-card ai-score">
                <div className="insight-icon">
                  <i className="fas fa-microchip"></i>
                </div>
                <div className="insight-content">
                  <span className="insight-label">AI Score</span>
                  <div className="score-wrapper">
                    <span className="score-value">{displayData.ai_score || 'N/A'}</span>
                    <span className="score-max">/100</span>
                  </div>
                  <div className="progress-bar">
                    <div className="progress-fill" style={{ width: `${displayData.ai_score || 0}%` }}></div>
                  </div>
                </div>
              </div>

              <div className="insight-card">
                <div className="insight-icon">
                  <i className="fas fa-bullhorn"></i>
                </div>
                <div className="insight-content">
                  <span className="insight-label">Recommendation</span>
                  <span className={`recommendation-badge ${(displayData.recommendation || '').toLowerCase().replace(' ', '-')}`}>
                    {displayData.recommendation || 'N/A'}
                  </span>
                </div>
              </div>

              <div className="insight-card">
                <div className="insight-icon">
                  <i className="fas fa-shield-alt"></i>
                </div>
                <div className="insight-content">
                  <span className="insight-label">Risk Level</span>
                  <span className={`risk-level ${(displayData.risk_level || '').toLowerCase().replace(' ', '-')}`}>
                    {displayData.risk_level || 'N/A'}
                  </span>
                </div>
              </div>

              <div className="insight-card">
                <div className="insight-icon">
                  <i className="fas fa-chart-pie"></i>
                </div>
                <div className="insight-content">
                  <span className="insight-label">Valuation</span>
                  <span className="valuation">{displayData.valuation || 'N/A'}</span>
                </div>
              </div>
            </div>

            <div className="growth-section">
              <div className="growth-icon">
                <i className="fas fa-seedling"></i>
              </div>
              <div className="growth-content">
                <span className="growth-label">Growth Potential</span>
                <span className="growth-value">{displayData.growth_potential || 'N/A'}</span>
              </div>
              {/* FIXED: growth metrics — only render a metric when it's a
                  real finite number. The old `&&` guard rendered
                  "Earnings Growth: %" whenever the backend sent a string
                  like "%" or when a value like 0 was treated as falsy
                  (silently hiding a real 0% growth row). */}
              {displayData.growth_metrics && (
                <div className="growth-metrics">
                  {isRenderableGrowth(displayData.growth_metrics.revenue_growth) && (
                    <span className="growth-metric">
                      Revenue Growth: {formatGrowth(displayData.growth_metrics.revenue_growth)}%
                    </span>
                  )}
                  {isRenderableGrowth(displayData.growth_metrics.earnings_growth) && (
                    <span className="growth-metric">
                      Earnings Growth: {formatGrowth(displayData.growth_metrics.earnings_growth)}%
                    </span>
                  )}
                  {isRenderableGrowth(displayData.growth_metrics.earnings_quarterly_growth) && (
                    <span className="growth-metric">
                      Quarterly Growth: {formatGrowth(displayData.growth_metrics.earnings_quarterly_growth)}%
                    </span>
                  )}
                </div>
              )}
            </div>
          </div>

          {/* Metrics Grid */}
          <div className="metrics-section glass-card">
            <div className="metrics-header">
              <i className="fas fa-cubes"></i>
              <h3>Key Financial Metrics</h3>
            </div>
            <div className="metrics-grid">
              <div className="metric-card">
                <span className="metric-label">Market Cap</span>
                <span className="metric-value">{formatLargeNumber(displayData.market_cap)}</span>
              </div>
              
              <div className="metric-card">
                <span className="metric-label">P/E Ratio</span>
                <span className="metric-value">{fmt(displayData.pe_ratio)}</span>
              </div>
              
              <div className="metric-card">
                <span className="metric-label">P/B Ratio</span>
                <span className="metric-value">{fmt(displayData.pb_ratio)}</span>
              </div>
              
              <div className="metric-card">
                <span className="metric-label">EPS</span>
                <span className="metric-value">{fmt(displayData.eps, { prefix: currency })}</span>
              </div>
              
              <div className="metric-card">
                <span className="metric-label">ROE</span>
                <span className="metric-value">{fmt(displayData.roe, { suffix: '%' })}</span>
              </div>
              
              <div className="metric-card">
                <span className="metric-label">Div Yield</span>
                <span className="metric-value">{fmt(displayData.dividend_yield, { suffix: '%' })}</span>
              </div>
              
              <div className="metric-card">
                <span className="metric-label">D/E Ratio</span>
                <span className="metric-value">{fmt(displayData.debt_to_equity)}</span>
              </div>
              
              <div className="metric-card">
                <span className="metric-label">Volatility</span>
                <span className="metric-value">
                  {isNum(displayData.volatility) ? `${(displayData.volatility * 100).toFixed(1)}%` : 'N/A'}
                </span>
              </div>
              
              <div className="metric-card">
                <span className="metric-label">52W High</span>
                <span className="metric-value">{displayData.fifty_two_week_high ? fmt(displayData.fifty_two_week_high, { prefix: currency }) : 'N/A'}</span>
              </div>
              
              <div className="metric-card">
                <span className="metric-label">52W Low</span>
                <span className="metric-value">{displayData.fifty_two_week_low ? fmt(displayData.fifty_two_week_low, { prefix: currency }) : 'N/A'}</span>
              </div>
              
              <div className="metric-card">
                <span className="metric-label">Avg Volume</span>
                <span className="metric-value">{displayData.average_volume ? `${(displayData.average_volume / 1e6).toFixed(2)}M` : 'N/A'}</span>
              </div>
            </div>
          </div>

          {/* Technical Indicators */}
          {displayData.technical_indicators && Object.keys(displayData.technical_indicators).length > 0 && (
            <div className="technical-section glass-card">
              <div className="technical-header">
                <i className="fas fa-wave-square"></i>
                <h3>Technical Analysis</h3>
              </div>
              <div className="technical-grid">
                {isNum(displayData.technical_indicators.rsi) && (
                  <div className="technical-card">
                    <span className="technical-label">RSI (14)</span>
                    <span className="technical-value">{displayData.technical_indicators.rsi.toFixed(2)}</span>
                    <div className="rsi-indicator">
                      <div 
                        className="rsi-bar" 
                        style={{ 
                          width: `${displayData.technical_indicators.rsi}%`,
                          background: displayData.technical_indicators.rsi > 70 ? '#ef4444' : 
                                     displayData.technical_indicators.rsi < 30 ? '#10b981' : '#f59e0b'
                        }}
                      ></div>
                    </div>
                  </div>
                )}
                {isNum(displayData.technical_indicators.sma_20) && (
                  <div className="technical-card">
                    <span className="technical-label">SMA 20</span>
                    <span className="technical-value">{fmt(displayData.technical_indicators.sma_20, { prefix: currency })}</span>
                  </div>
                )}
                {isNum(displayData.technical_indicators.sma_50) && (
                  <div className="technical-card">
                    <span className="technical-label">SMA 50</span>
                    <span className="technical-value">{fmt(displayData.technical_indicators.sma_50, { prefix: currency })}</span>
                  </div>
                )}
                {isNum(displayData.technical_indicators.sma_200) && (
                  <div className="technical-card">
                    <span className="technical-label">SMA 200</span>
                    <span className="technical-value">{fmt(displayData.technical_indicators.sma_200, { prefix: currency })}</span>
                  </div>
                )}
                {isNum(displayData.technical_indicators.macd) && (
                  <div className="technical-card">
                    <span className="technical-label">MACD</span>
                    <span className="technical-value">
                      {displayData.technical_indicators.macd.toFixed(2)}
                      {isNum(displayData.technical_indicators.signal) && ` / ${displayData.technical_indicators.signal.toFixed(2)}`}
                    </span>
                  </div>
                )}
                {displayData.technical_indicators.trend && (
                  <div className="technical-card trend">
                    <span className="technical-label">Trend</span>
                    <span className={`trend-value ${displayData.technical_indicators.trend.toLowerCase().includes('bull') ? 'bullish' : 'bearish'}`}>
                      <i className={`fas fa-${displayData.technical_indicators.trend.toLowerCase().includes('bull') ? 'arrow-up' : 'arrow-down'}`}></i>
                      {displayData.technical_indicators.trend}
                    </span>
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default StockForm;