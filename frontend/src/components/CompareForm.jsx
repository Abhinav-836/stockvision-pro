import React, { useState } from 'react';
import { compareStocks, getStockChartData } from '../api';
import CompareChart from './CompareChart';

function CompareForm() {
  const [symbols, setSymbols] = useState(['', '']);
  const [loading, setLoading] = useState(false);
  const [chartLoading, setChartLoading] = useState(false);
  const [data, setData] = useState(null);
  const [aiData, setAiData] = useState(null);
  const [error, setError] = useState('');
  const [chartData, setChartData] = useState({});
  const [chartPeriod, setChartPeriod] = useState('3mo');
  const [comparisonType, setComparisonType] = useState('standard'); // 'standard' or 'ai'

  const periods = [
    { value: '1d', label: '1D' },
    { value: '5d', label: '5D' },
    { value: '1mo', label: '1M' },
    { value: '3mo', label: '3M' },
    { value: '6mo', label: '6M' },
    { value: '1y', label: '1Y' },
  ];

  const handleAddSymbol = () => {
    if (symbols.length < 5) {
      setSymbols([...symbols, '']);
    }
  };

  const handleRemoveSymbol = (index) => {
    if (symbols.length > 2) {
      setSymbols(symbols.filter((_, i) => i !== index));
      setData(null);
      setAiData(null);
      setChartData({});
    }
  };

  const handleSymbolChange = (index, value) => {
    const newSymbols = [...symbols];
    newSymbols[index] = value.toUpperCase().replace(/[^A-Z.]/g, '').slice(0, 10);
    setSymbols(newSymbols);
    setError('');
    setData(null);
    setAiData(null);
    setChartData({});
  };

  const validateSymbols = () => {
    const valid = symbols.filter(s => s.trim());
    if (valid.length < 2) {
      setError('Please enter at least 2 symbols');
      return null;
    }
    if (new Set(valid).size !== valid.length) {
      setError('Duplicate symbols detected');
      return null;
    }
    return valid;
  };

  const fetchChartData = async (symbolsToFetch, period = chartPeriod) => {
    if (!symbolsToFetch || symbolsToFetch.length === 0) return;
    
    setChartLoading(true);
    const charts = {};
    await Promise.all(
      symbolsToFetch.map(async (symbol) => {
        try {
          const data = await getStockChartData(symbol, period);
          charts[symbol] = data;
        } catch (error) {
          console.error(`Error fetching chart for ${symbol}:`, error);
          charts[symbol] = [];
        }
      })
    );
    setChartData(charts);
    setChartLoading(false);
  };

  const handlePeriodChange = async (period) => {
    setChartPeriod(period);
    const valid = symbols.filter(s => s.trim());
    if (valid.length >= 2) {
      await fetchChartData(valid, period);
    }
  };

  const handleCompare = async () => {
    const valid = validateSymbols();
    if (!valid) return;

    setLoading(true);
    setError('');
    setData(null);
    setAiData(null);

    try {
      const result = await compareStocks(valid);
      setData(result);
      
      // Extract AI analysis if available
      if (result.ai_analysis) {
        setAiData(result.ai_analysis);
        setComparisonType('ai');
      } else {
        setComparisonType('standard');
      }
      
      await fetchChartData(valid);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="compare-analysis">
      {/* Input Section */}
      <div className="compare-input-section glass-card">
        <h3 className="section-title">
          <i className="fas fa-code-branch"></i>
          <span>AI-Powered Stock Comparison</span>
        </h3>

        <div className="symbols-list">
          {symbols.map((symbol, index) => (
            <div key={index} className="symbol-input-row">
              <div className="input-wrapper">
                <i className="fas fa-search input-icon"></i>
                <input
                  type="text"
                  value={symbol}
                  onChange={(e) => handleSymbolChange(index, e.target.value)}
                  placeholder={`Stock ${index + 1} (e.g., AAPL)`}
                  disabled={loading || chartLoading}
                />
                {index === 0 && <span className="input-badge">Primary</span>}
              </div>
              {symbols.length > 2 && (
                <button
                  onClick={() => handleRemoveSymbol(index)}
                  className="remove-symbol-btn"
                  disabled={loading || chartLoading}
                >
                  <i className="fas fa-times"></i>
                </button>
              )}
            </div>
          ))}
        </div>

        <div className="compare-actions">
          {symbols.length < 5 && (
            <button
              onClick={handleAddSymbol}
              disabled={loading || chartLoading}
              className="add-symbol-btn"
            >
              <i className="fas fa-plus"></i>
              Add Stock
            </button>
          )}
          
          <button
            onClick={handleCompare}
            disabled={loading || chartLoading}
            className="ai-compare-btn"
          >
            {loading ? (
              <>
                <i className="fas fa-spinner fa-spin"></i>
                <span>AI Analyzing...</span>
              </>
            ) : (
              <>
                <i className="fas fa-brain"></i>
                <span>AI Compare</span>
              </>
            )}
          </button>
        </div>

        {error && (
          <div className="error-message">
            <i className="fas fa-exclamation-circle"></i>
            <span>{error}</span>
          </div>
        )}
      </div>

      {/* Comparison Chart */}
      {Object.keys(chartData).length > 0 && (
        <div className="chart-section glass-card">
          <div className="chart-header">
            <div className="chart-title">
              <i className="fas fa-chart-line"></i>
              <h3>Price Comparison</h3>
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
          {chartLoading ? (
            <div className="chart-container" style={{ height: '400px', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <div className="loading-spinner"></div>
              <p style={{ color: 'var(--text-secondary)', marginLeft: '10px' }}>Loading chart data...</p>
            </div>
          ) : (
            <CompareChart chartData={chartData} />
          )}
        </div>
      )}

      {/* AI Analysis Results */}
      {aiData && comparisonType === 'ai' && (
        <div className="ai-analysis-card glass-card">
          <div className="ai-analysis-header">
            <i className="fas fa-brain"></i>
            <h3>AI-Powered Analysis</h3>
          </div>

          <div className="ai-comparison-grid">
            <div className="ai-comparison-item">
              <div className="ai-comparison-label">Best for Growth</div>
              <div className="ai-comparison-value">{aiData.best_for_growth || 'N/A'}</div>
            </div>
            <div className="ai-comparison-item">
              <div className="ai-comparison-label">Best for Value</div>
              <div className="ai-comparison-value">{aiData.best_for_value || 'N/A'}</div>
            </div>
            <div className="ai-comparison-item">
              <div className="ai-comparison-label">Best for Income</div>
              <div className="ai-comparison-value">{aiData.best_for_income || 'N/A'}</div>
            </div>
            <div className="ai-comparison-item">
              <div className="ai-comparison-label">Safest Option</div>
              <div className="ai-comparison-value">{aiData.safest_option || 'N/A'}</div>
            </div>
            <div className="ai-comparison-item highlight">
              <div className="ai-comparison-label">Top Pick</div>
              <div className="ai-comparison-value">{aiData.overall_recommendation || 'N/A'}</div>
            </div>
          </div>

          {aiData.analysis && (
            <div className="ai-analysis-text">
              <h4>Analysis</h4>
              <p>{aiData.analysis}</p>
            </div>
          )}

          {aiData.risk_assessment && (
            <div className="ai-risk-text">
              <h4>Risk Assessment</h4>
              <p>{aiData.risk_assessment}</p>
            </div>
          )}
        </div>
      )}

      {/* Standard Comparison Results */}
      {data && data.stocks && comparisonType === 'standard' && (
        <div className="comparison-results">
          {/* Summary Cards */}
          <div className="comparison-summary">
            <div className="summary-card ai-pick">
              <div className="summary-label">AI Top Pick</div>
              <div className="summary-value">{data.comparison.ai_top_pick}</div>
            </div>
            <div className="summary-card value">
              <div className="summary-label">Best Value</div>
              <div className="summary-value">{data.comparison.best_value}</div>
            </div>
            <div className="summary-card dividend">
              <div className="summary-label">Best Dividend</div>
              <div className="summary-value">{data.comparison.best_dividend}</div>
            </div>
            <div className="summary-card risk">
              <div className="summary-label">Lowest Risk</div>
              <div className="summary-value">{data.comparison.lowest_risk}</div>
            </div>
          </div>

          {/* Comparison Table */}
          <div className="comparison-table-wrapper">
            <table className="comparison-table">
              <thead>
                <tr>
                  <th>Metric</th>
                  {data.stocks.map(stock => (
                    <th key={stock.symbol}>{stock.symbol}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td>Company</td>
                  {data.stocks.map(stock => (
                    <td key={stock.symbol}>{stock.company_name}</td>
                  ))}
                </tr>
                <tr>
                  <td>Price</td>
                  {data.stocks.map(stock => (
                    <td key={stock.symbol}>${stock.current_price?.toFixed(2)}</td>
                  ))}
                </tr>
                <tr>
                  <td>Change %</td>
                  {data.stocks.map(stock => (
                    <td key={stock.symbol} className={stock.change_percent >= 0 ? 'positive' : 'negative'}>
                      {stock.change_percent >= 0 ? '+' : ''}{stock.change_percent?.toFixed(2)}%
                    </td>
                  ))}
                </tr>
                <tr className="highlight-row">
                  <td>AI Score</td>
                  {data.stocks.map(stock => (
                    <td key={stock.symbol}>
                      <div className="score-cell">
                        <span>{stock.ai_score}</span>
                        <div className="score-bar">
                          <div className="score-fill" style={{ width: `${stock.ai_score}%` }}></div>
                        </div>
                      </div>
                    </td>
                  ))}
                </tr>
                <tr>
                  <td>P/E Ratio</td>
                  {data.stocks.map(stock => (
                    <td key={stock.symbol}>{stock.pe_ratio || 'N/A'}</td>
                  ))}
                </tr>
                <tr>
                  <td>Dividend Yield</td>
                  {data.stocks.map(stock => (
                    <td key={stock.symbol}>{stock.dividend_yield ? `${stock.dividend_yield}%` : 'N/A'}</td>
                  ))}
                </tr>
                <tr>
                  <td>ROE</td>
                  {data.stocks.map(stock => (
                    <td key={stock.symbol}>{stock.roe ? `${stock.roe}%` : 'N/A'}</td>
                  ))}
                </tr>
                <tr>
                  <td>Debt/Equity</td>
                  {data.stocks.map(stock => (
                    <td key={stock.symbol}>{stock.debt_to_equity ?? 'N/A'}</td>
                  ))}
                </tr>
                <tr>
                  <td>Market Cap</td>
                  {data.stocks.map(stock => (
                    <td key={stock.symbol}>
                      {stock.market_cap ? `$${(stock.market_cap / 1e9).toFixed(2)}B` : 'N/A'}
                    </td>
                  ))}
                </tr>
              </tbody>
            </table>
          </div>

          {/* Average Metrics */}
          <div className="comparison-average">
            <h4 className="average-title">Average Metrics</h4>
            <div className="average-grid">
              <div className="average-item">
                <div className="average-label">Avg P/E</div>
                <div className="average-value">{data.comparison.average_pe}</div>
              </div>
              <div className="average-item">
                <div className="average-label">Avg ROE</div>
                <div className="average-value">{data.comparison.average_roe}%</div>
              </div>
              <div className="average-item">
                <div className="average-label">Avg Debt/Equity</div>
                <div className="average-value">{data.comparison.average_debt}</div>
              </div>
              <div className="average-item">
                <div className="average-label">Stocks</div>
                <div className="average-value">{data.stocks.length}</div>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default CompareForm;