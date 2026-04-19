import React, { useState, useEffect } from 'react';
import StockForm from './components/StockForm';
import CompareForm from './components/CompareForm';
import MarketOverview from './components/MarketOverview';
import './App.css';

function App() {
  const [activeTab, setActiveTab] = useState('analyze');
  const [watchlist, setWatchlist] = useState([]);
  const [isDarkMode, setIsDarkMode] = useState(() => {
    // Check localStorage for theme preference
    const savedTheme = localStorage.getItem('theme');
    return savedTheme ? savedTheme === 'dark' : true;
  });

  useEffect(() => {
    loadWatchlist();
    // Apply theme on initial load
    applyTheme(isDarkMode);
  }, []);

  useEffect(() => {
    applyTheme(isDarkMode);
    localStorage.setItem('theme', isDarkMode ? 'dark' : 'light');
  }, [isDarkMode]);

  const applyTheme = (dark) => {
    if (dark) {
      document.body.classList.remove('light-mode');
      document.documentElement.style.setProperty('--bg-primary', '#0a0c10');
      document.documentElement.style.setProperty('--bg-secondary', '#111318');
      document.documentElement.style.setProperty('--bg-card', '#1a1d24');
      document.documentElement.style.setProperty('--text-primary', '#ffffff');
      document.documentElement.style.setProperty('--text-secondary', '#9ca3af');
      document.documentElement.style.setProperty('--border', '#2a2e36');
    } else {
      document.body.classList.add('light-mode');
      document.documentElement.style.setProperty('--bg-primary', '#f3f4f6');
      document.documentElement.style.setProperty('--bg-secondary', '#ffffff');
      document.documentElement.style.setProperty('--bg-card', '#ffffff');
      document.documentElement.style.setProperty('--text-primary', '#111827');
      document.documentElement.style.setProperty('--text-secondary', '#4b5563');
      document.documentElement.style.setProperty('--border', '#e5e7eb');
    }
  };

  const loadWatchlist = () => {
    try {
      const saved = localStorage.getItem('watchlist');
      if (saved) {
        setWatchlist(JSON.parse(saved));
      }
    } catch (error) {
      console.error('Error loading watchlist:', error);
    }
  };

  const addToWatchlist = (symbol) => {
    const updated = [...new Set([...watchlist, symbol.toUpperCase()])];
    setWatchlist(updated);
    localStorage.setItem('watchlist', JSON.stringify(updated));
  };

  const removeFromWatchlist = (symbol) => {
    const updated = watchlist.filter(s => s !== symbol);
    setWatchlist(updated);
    localStorage.setItem('watchlist', JSON.stringify(updated));
  };

  const toggleTheme = () => {
    setIsDarkMode(!isDarkMode);
  };

  return (
    <div className={`app ${isDarkMode ? 'dark' : 'light'}`}>
      {/* Animated Background */}
      <div className="gradient-bg">
        <div className="gradient-1"></div>
        <div className="gradient-2"></div>
        <div className="gradient-3"></div>
      </div>

      {/* Header */}
      <header className="glass-header">
        <div className="header-content">
          <div className="logo-section">
            <div className="logo-wrapper">
              <div className="logo-glow"></div>
              <i className="fas fa-chart-line"></i>
            </div>
            <div className="brand-text">
              <h1>StockVision<span>Pro</span></h1>
              <p>AI-Powered Investment Intelligence</p>
            </div>
          </div>

          <div className="header-actions">
            <button className="theme-toggle" onClick={toggleTheme}>
              <i className={`fas fa-${isDarkMode ? 'sun' : 'moon'}`}></i>
            </button>
            <div className="ai-badge">
              <i className="fas fa-brain"></i>
              <span>AI Powered</span>
              <div className="badge-glow"></div>
            </div>
          </div>
        </div>

        {/* Navigation */}
        <nav className="glass-nav">
          <button
            className={`nav-item ${activeTab === 'analyze' ? 'active' : ''}`}
            onClick={() => setActiveTab('analyze')}
          >
            <i className="fas fa-search"></i>
            <span>Analyze</span>
            {activeTab === 'analyze' && <div className="active-indicator"></div>}
          </button>
          <button
            className={`nav-item ${activeTab === 'compare' ? 'active' : ''}`}
            onClick={() => setActiveTab('compare')}
          >
            <i className="fas fa-balance-scale"></i>
            <span>Compare</span>
            {activeTab === 'compare' && <div className="active-indicator"></div>}
          </button>
          <button
            className={`nav-item ${activeTab === 'watchlist' ? 'active' : ''}`}
            onClick={() => setActiveTab('watchlist')}
          >
            <i className="fas fa-star"></i>
            <span>Watchlist</span>
            {watchlist.length > 0 && <span className="badge">{watchlist.length}</span>}
            {activeTab === 'watchlist' && <div className="active-indicator"></div>}
          </button>
        </nav>
      </header>

      {/* Market Overview Ticker */}
      <MarketOverview />

      {/* Main Content */}
      <main className="main-content">
        <div className="container">
          {/* Page Header with Animation */}
          <div className="page-header fade-in">
            <h2>
              {activeTab === 'analyze' && (
                <>
                  <i className="fas fa-microscope"></i>
                  <span>Deep Stock Analysis</span>
                </>
              )}
              {activeTab === 'compare' && (
                <>
                  <i className="fas fa-code-branch"></i>
                  <span>AI-Powered Comparison</span>
                </>
              )}
              {activeTab === 'watchlist' && (
                <>
                  <i className="fas fa-star"></i>
                  <span>Your Watchlist</span>
                </>
              )}
            </h2>
            <p>
              {activeTab === 'analyze' && "Get comprehensive AI-powered insights for any stock"}
              {activeTab === 'compare' && "Side-by-side AI analysis with interactive charts"}
              {activeTab === 'watchlist' && "Track and monitor your favorite stocks"}
            </p>
          </div>

          {/* Content */}
          <div className="content-wrapper slide-up">
            {activeTab === 'analyze' && (
              <StockForm onAddToWatchlist={addToWatchlist} watchlist={watchlist} />
            )}

            {activeTab === 'compare' && (
              <CompareForm />
            )}

            {activeTab === 'watchlist' && (
              <div className="watchlist-container">
                {watchlist.length === 0 ? (
                  <div className="empty-state">
                    <div className="empty-icon">
                      <i className="fas fa-star"></i>
                    </div>
                    <h3>Your watchlist is empty</h3>
                    <p>Start by analyzing stocks and adding them to your watchlist</p>
                    <button className="primary-btn" onClick={() => setActiveTab('analyze')}>
                      <i className="fas fa-search"></i>
                      Analyze Stocks
                    </button>
                  </div>
                ) : (
                  <div className="watchlist-grid">
                    {watchlist.map(symbol => (
                      <div key={symbol} className="watchlist-card glass-card">
                        <div className="card-header">
                          <h3>{symbol}</h3>
                          <button 
                            className="remove-btn"
                            onClick={() => removeFromWatchlist(symbol)}
                          >
                            <i className="fas fa-times"></i>
                          </button>
                        </div>
                        <button 
                          className="analyze-btn"
                          onClick={() => {
                            setActiveTab('analyze');
                            setTimeout(() => {
                              const event = new CustomEvent('analyzeStock', { detail: symbol });
                              window.dispatchEvent(event);
                            }, 100);
                          }}
                        >
                          <i className="fas fa-chart-line"></i>
                          Analyze
                        </button>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      </main>

      {/* Footer */}
      <footer className="glass-footer">
        <div className="container">
          <div className="footer-content">
          <p>© 2025 StockVision Pro by StrattonTrade. AI-powered insights for smarter investing.</p>
            <div className="footer-links">
              <span><i className="fas fa-shield-alt"></i> Not A Financial Advice</span>
              <span><i className="fas fa-robot"></i> AI-Generated Insights</span>
              <span><i className="fas fa-database"></i> Real-Time Data</span>
            </div>
          </div>
        </div>
      </footer>
    </div>
  );
}

export default App;