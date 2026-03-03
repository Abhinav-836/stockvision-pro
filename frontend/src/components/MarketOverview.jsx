import React, { useState, useEffect } from 'react';
import { getMarketIndices } from '../api';

function MarketOverview() {
  const [indices, setIndices] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchIndices();
    const interval = setInterval(fetchIndices, 60000);
    return () => clearInterval(interval);
  }, []);

  const fetchIndices = async () => {
    try {
      const data = await getMarketIndices();
      setIndices(data);
    } catch (error) {
      console.error('Error fetching indices:', error);
    } finally {
      setLoading(false);
    }
  };

  if (loading || indices.length === 0) return null;

  return (
    <div className="market-ticker">
      <div className="ticker-wrapper">
        <div className="ticker-content">
          {[...indices, ...indices].map((index, i) => (
            <div key={i} className="ticker-item">
              <span className="index-name">{index.name}</span>
              <span className="index-value">{index.value?.toFixed(2)}</span>
              <span className={`index-change ${index.change >= 0 ? 'positive' : 'negative'}`}>
                <i className={`fas fa-${index.change >= 0 ? 'caret-up' : 'caret-down'}`}></i>
                {Math.abs(index.change).toFixed(2)}%
              </span>
            </div>
          ))}
        </div>
        <div className="ticker-gradient-left"></div>
        <div className="ticker-gradient-right"></div>
      </div>
    </div>
  );
}

export default MarketOverview;