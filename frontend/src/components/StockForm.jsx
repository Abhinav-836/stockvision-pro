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

  const { price: realtimePrice, change: realtimeChange, connected } = useRealtimePrice(
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
      console.log('📊 API Response:', data);
      setStockData(data);
      await fetchChartData(cleanSymbol, chartPeriod);
    } catch (err) {
      console.error('❌ API Error:', err);
      setError(err.message || 'Failed to fetch stock data');
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
    if (num === null || num === undefined) return 'N/A';
    if (num === 0) return '$0';
    if (num >= 1e12) return `$${(num / 1e12).toFixed(2)}T`;
    if (num >= 1e9) return `$${(num / 1e9).toFixed(2)}B`;
    if (num >= 1e6) return `$${(num / 1e6).toFixed(2)}M`;
    if (num >= 1e3) return `$${(num / 1e3).toFixed(2)}K`;
    if (typeof num === 'number' && !isNaN(num)) return `$${num.toFixed(2)}`;
    return 'N/A';
  };

  // FIXED: Safer formatLargeNumber function
  const formatLargeNumber = (num) => {
    if (num === null || num === undefined) return 'N/A';
    const parsedNum = typeof num === 'number' ? num : parseFloat(num);
    if (isNaN(parsedNum) || parsedNum === 0) return 'N/A';
    if (parsedNum >= 1e12) return `$${(parsedNum / 1e12).toFixed(2)}T`;
    if (parsedNum >= 1e9) return `$${(parsedNum / 1e9).toFixed(2)}B`;
    if (parsedNum >= 1e6) return `$${(parsedNum / 1e6).toFixed(2)}M`;
    return `$${parsedNum.toFixed(0)}`;
  };

  const isInWatchlist = stockData && watchlist.includes(stockData.symbol);

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
                onClick={() => handleSearch(testSymbol)}
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
              {displayData.growth_metrics?.revenue_growth && (
                <div className="growth-metrics">
                  <span className="growth-metric">
                    Revenue Growth: {displayData.growth_metrics.revenue_growth}%
                  </span>
                  <span className="growth-metric">
                    Earnings Growth: {displayData.growth_metrics.earnings_growth}%
                  </span>
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
                <span className="metric-value">{displayData.pe_ratio?.toFixed(2) || 'N/A'}</span>
              </div>
              
              <div className="metric-card">
                <span className="metric-label">P/B Ratio</span>
                <span className="metric-value">{displayData.pb_ratio?.toFixed(2) || 'N/A'}</span>
              </div>
              
              <div className="metric-card">
                <span className="metric-label">EPS</span>
                <span className="metric-value">{displayData.eps ? `$${displayData.eps.toFixed(2)}` : 'N/A'}</span>
              </div>
              
              <div className="metric-card">
                <span className="metric-label">ROE</span>
                <span className="metric-value">{displayData.roe ? `${displayData.roe.toFixed(2)}%` : 'N/A'}</span>
              </div>
              
              <div className="metric-card">
                <span className="metric-label">Div Yield</span>
                <span className="metric-value">{displayData.dividend_yield ? `${displayData.dividend_yield.toFixed(2)}%` : '0%'}</span>
              </div>
              
              <div className="metric-card">
                <span className="metric-label">D/E Ratio</span>
                <span className="metric-value">{displayData.debt_to_equity?.toFixed(2) || 'N/A'}</span>
              </div>
              
              <div className="metric-card">
                <span className="metric-label">Volatility</span>
                <span className="metric-value">{displayData.volatility?.toFixed(2) || 'N/A'}</span>
              </div>
              
              <div className="metric-card">
                <span className="metric-label">52W High</span>
                <span className="metric-value">{displayData.fifty_two_week_high ? `$${displayData.fifty_two_week_high.toFixed(2)}` : 'N/A'}</span>
              </div>
              
              <div className="metric-card">
                <span className="metric-label">52W Low</span>
                <span className="metric-value">{displayData.fifty_two_week_low ? `$${displayData.fifty_two_week_low.toFixed(2)}` : 'N/A'}</span>
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
                {displayData.technical_indicators.rsi && (
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
                {displayData.technical_indicators.sma_20 && (
                  <div className="technical-card">
                    <span className="technical-label">SMA 20</span>
                    <span className="technical-value">${displayData.technical_indicators.sma_20.toFixed(2)}</span>
                  </div>
                )}
                {displayData.technical_indicators.sma_50 && (
                  <div className="technical-card">
                    <span className="technical-label">SMA 50</span>
                    <span className="technical-value">${displayData.technical_indicators.sma_50.toFixed(2)}</span>
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