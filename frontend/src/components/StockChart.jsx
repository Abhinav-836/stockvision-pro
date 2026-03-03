import React, { useMemo, useState } from 'react';
import {
  Area,
  Line,
  ComposedChart,
  CartesianGrid,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine
} from 'recharts';

function StockChart({ history = [], symbol = 'Stock', currentPrice = null, isLoading = false }) {
  const [expanded, setExpanded] = useState(false);

  const data = useMemo(() => {
    if (!Array.isArray(history) || history.length === 0) return [];
    
    return history
      .map(item => {
        let date = item.date;
        if (!date && item.time) date = item.time;
        if (!date) return null;
        
        if (typeof date === 'number' && String(date).length === 10) {
          date = date * 1000;
        }
        
        try {
          const dateObj = new Date(date);
          if (isNaN(dateObj.getTime())) return null;
          
          const price = Number(item.price || item.close || item.value);
          if (isNaN(price) || price <= 0) return null;
          
          return {
            date: dateObj.toISOString(),
            price
          };
        } catch {
          return null;
        }
      })
      .filter(Boolean)
      .sort((a, b) => new Date(a.date) - new Date(b.date));
  }, [history]);

  const stats = useMemo(() => {
    if (data.length === 0) return null;
    
    const prices = data.map(d => d.price);
    const first = prices[0];
    const last = prices[prices.length - 1];
    const min = Math.min(...prices);
    const max = Math.max(...prices);
    const change = first ? ((last - first) / first) * 100 : 0;
    const padding = (max - min) * 0.05;
    
    return {
      first,
      last,
      min: Math.max(0, min - padding),
      max: max + padding,
      change,
      isPositive: change >= 0
    };
  }, [data]);

  if (isLoading) {
    return (
      <div className="chart-container" style={{ height: '400px', display: 'flex', alignItems: 'center', justifyContent: 'center', flexDirection: 'column' }}>
        <div className="loading-spinner" style={{ width: '40px', height: '40px', borderWidth: '3px' }}></div>
        <p style={{ color: 'var(--text-secondary)', marginTop: '20px' }}>Loading chart data...</p>
      </div>
    );
  }

  if (!stats || data.length === 0) {
    return (
      <div className="chart-container" style={{ height: '400px', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <p style={{ color: 'var(--text-secondary)' }}>No chart data available</p>
      </div>
    );
  }

  const CustomTooltip = ({ active, payload, label }) => {
    if (active && payload && payload.length) {
      const value = payload[0].value;
      const date = new Date(label).toLocaleDateString('en-IN', {
        day: 'numeric',
        month: 'short',
        year: 'numeric'
      });

      const diff = currentPrice ? value - currentPrice : null;
      const pctDiff = currentPrice && currentPrice !== 0 ? (diff / currentPrice) * 100 : null;

      return (
        <div className="custom-tooltip">
          <div className="tooltip-date">{date}</div>
          <div className="tooltip-price">${value.toFixed(2)}</div>
          {diff !== null && pctDiff !== null && (
            <div className={`tooltip-change ${diff >= 0 ? 'positive' : 'negative'}`}>
              {diff >= 0 ? '▲' : '▼'} ${Math.abs(diff).toFixed(2)} ({pctDiff >= 0 ? '+' : ''}{pctDiff.toFixed(2)}%)
            </div>
          )}
        </div>
      );
    }
    return null;
  };

  const formatXAxis = (tick) => {
    const date = new Date(tick);
    return date.toLocaleDateString('en-IN', { day: 'numeric', month: 'short' });
  };

  return (
    <div className="chart-container">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={data} margin={{ top: 10, right: 30, left: 20, bottom: 10 }}>
          <defs>
            <linearGradient id="colorPrice" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor="#6366f1" stopOpacity={0.3} />
              <stop offset="95%" stopColor="#6366f1" stopOpacity={0} />
            </linearGradient>
          </defs>

          <CartesianGrid strokeDasharray="3 3" stroke="#2a2e36" vertical={false} />

          <XAxis
            dataKey="date"
            tickFormatter={formatXAxis}
            tick={{ fill: '#9ca3af', fontSize: 12 }}
            axisLine={{ stroke: '#2a2e36' }}
            tickLine={{ stroke: '#2a2e36' }}
          />

          <YAxis
            tickFormatter={(v) => `$${v.toFixed(0)}`}
            tick={{ fill: '#9ca3af', fontSize: 12 }}
            axisLine={{ stroke: '#2a2e36' }}
            tickLine={{ stroke: '#2a2e36' }}
            domain={[stats.min, stats.max]}
          />

          <Tooltip content={<CustomTooltip />} />

          {currentPrice && (
            <ReferenceLine
              y={currentPrice}
              stroke="#6b7280"
              strokeDasharray="3 3"
              label={{
                value: 'Current',
                position: 'right',
                fill: '#6b7280',
                fontSize: 10
              }}
            />
          )}

          <Area
            type="monotone"
            dataKey="price"
            stroke="none"
            fill="url(#colorPrice)"
          />
          
          <Line
            type="monotone"
            dataKey="price"
            stroke="#6366f1"
            strokeWidth={2}
            dot={false}
            activeDot={{ r: 6, fill: '#6366f1', stroke: '#fff', strokeWidth: 2 }}
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

export default StockChart;