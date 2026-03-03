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

  // Use real-time price updates
  const { price: realtimePrice, change: realtimeChange } = useRealtimePrice(
    stockData?.symbol,
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

    try {
      const data = await getStockAnalysis(cleanSymbol);
      setStockData(data);
      await fetchChartData(cleanSymbol, chartPeriod);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
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
    if (stockData?.symbol) {
      await fetchChartData(stockData.symbol, period);
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

  const formatNumber = (num) => {
    if (!num && num !== 0) return 'N/A';
    if (num >= 1e12) return `$${(num / 1e12).toFixed(2)}T`;
    if (num >= 1e9) return `$${(num / 1e9).toFixed(2)}B`;
    if (num >= 1e6) return `$${(num / 1e6).toFixed(2)}M`;
    return `$${num.toFixed(2)}`;
  };

  const isInWatchlist = stockData && watchlist.includes(stockData.symbol);

  // Merge real-time data with stock data
  const displayData = stockData ? {
    ...stockData,
    current_price: realtimePrice ?? stockData.current_price,
    change_percent: realtimeChange ?? stockData.change_percent
  } : null;

  const metrics = [
    { key: 'market_cap', label: 'Market Cap', format: formatNumber },
    { key: 'pe_ratio', label: 'P/E Ratio', format: (v) => v?.toFixed(2) },
    { key: 'pb_ratio', label: 'P/B Ratio', format: (v) => v?.toFixed(2) },
    { key: 'eps', label: 'EPS', format: (v) => v ? `$${v.toFixed(2)}` : 'N/A' },
    { key: 'roe', label: 'ROE', format: (v) => v ? `${v.toFixed(2)}%` : 'N/A' },
    { key: 'dividend_yield', label: 'Div Yield', format: (v) => v ? `${v.toFixed(2)}%` : 'N/A' },
    { key: 'debt_to_equity', label: 'D/E', format: (v) => v?.toFixed(2) },
    { key: 'volatility', label: 'Volatility', format: (v) => v?.toFixed(2) },
    { key: 'fifty_two_week_high', label: '52W High', format: (v) => v ? `$${v}` : 'N/A' },
    { key: 'fifty_two_week_low', label: '52W Low', format: (v) => v ? `$${v}` : 'N/A' },
  ];

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
              <button
                type="button"
                className="clear-btn"
                onClick={() => setSymbol('')}
              >
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
                onClick={() => handleSearch(testSymbol)}
                disabled={loading}
                className="symbol-tag"
              >
                {testSymbol}
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
          {/* Stock Header */}
          <div className="stock-header glass-card">
            <div className="header-left">
              <div className="symbol-wrapper">
                <h1 className="stock-symbol">{displayData.symbol}</h1>
                <button
                  onClick={() => onAddToWatchlist(displayData.symbol)}
                  className={`watchlist-btn ${isInWatchlist ? 'active' : ''}`}
                >
                  <i className={`fas fa-star${isInWatchlist ? '' : '-regular'}`}></i>
                </button>
              </div>
              <div className="company-info">
                <h2 className="company-name">{displayData.company_name}</h2>
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
                      Indian Stock
                    </span>
                  )}
                </div>
              </div>
            </div>
            <div className="header-right">
              <div className="price-wrapper">
                <span className="current-price">${displayData.current_price?.toFixed(2)}</span>
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
                Confidence: {displayData.confidence || 'High'}
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
            </div>
          </div>

          {/* Metrics Grid */}
          <div className="metrics-section glass-card">
            <div className="metrics-header">
              <i className="fas fa-cubes"></i>
              <h3>Key Financial Metrics</h3>
            </div>
            <div className="metrics-grid">
              {metrics.map(({ key, label, format }) => {
                const value = displayData[key];
                if (value === null || value === undefined) return null;
                return (
                  <div key={key} className="metric-card">
                    <span className="metric-label">{label}</span>
                    <span className="metric-value">{format(value)}</span>
                  </div>
                );
              })}
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
                {displayData.technical_indicators.rsi && (
                  <div className="technical-card">
                    <span className="technical-label">RSI (14)</span>
                    <span className="technical-value">{displayData.technical_indicators.rsi}</span>
                    <div className="rsi-indicator">
                      <div className="rsi-bar" style={{ width: `${displayData.technical_indicators.rsi}%` }}></div>
                    </div>
                  </div>
                )}
                {displayData.technical_indicators.sma_20 && (
                  <div className="technical-card">
                    <span className="technical-label">SMA 20</span>
                    <span className="technical-value">${displayData.technical_indicators.sma_20}</span>
                  </div>
                )}
                {displayData.technical_indicators.sma_50 && (
                  <div className="technical-card">
                    <span className="technical-label">SMA 50</span>
                    <span className="technical-value">${displayData.technical_indicators.sma_50}</span>
                  </div>
                )}
                {displayData.technical_indicators.trend && (
                  <div className="technical-card trend">
                    <span className="technical-label">Trend</span>
                    <span className={`trend-value ${displayData.technical_indicators.trend.toLowerCase().includes('bull') ? 'bullish' : 'bearish'}`}>
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