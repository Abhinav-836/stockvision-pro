import React, { useMemo } from 'react';
import {
  Line,
  CartesianGrid,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Legend,
  ComposedChart
} from 'recharts';

function CompareChart({ chartData = {} }) {
  const colors = ['#6366f1', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6'];

  // FIXED: points were matched on the raw date STRING. Each data source
  // formats the same trading day differently — yFinance US bars are
  // "2026-10-01T00:00:00-04:00", yFinance/NSE Indian bars "...+05:30" or no
  // offset at all, Alpha Vantage just "2026-10-01" — so comparing two
  // stocks from different sources (or AAPL vs RELIANCE.NS) produced zero
  // matching dates. Every row had a value for only ONE stock and the lines
  // were drawn as scattered dots or not at all. Bars are now keyed by
  // their trading day (or day + hour for intraday 1D/5D charts), taken
  // from the string itself so no timezone conversion can shift the day,
  // and lines bridge the gaps where one exchange was closed.
  const keyFor = (date, intraday) => {
    const text = String(date);
    return intraday ? text.slice(0, 13) : text.slice(0, 10);
  };

  const combinedData = useMemo(() => {
    const symbols = Object.keys(chartData);
    if (symbols.length === 0) return [];

    // Intraday (1D/5D) if any series has more than one bar on the same day.
    const intraday = symbols.some(symbol => {
      const days = (chartData[symbol] || []).map(r => String(r?.date).slice(0, 10));
      return new Set(days).size < days.length;
    });

    const byKey = new Map();
    symbols.forEach(symbol => {
      (chartData[symbol] || []).forEach(item => {
        if (!item?.date) return;
        const price = Number(item.price);
        if (!isFinite(price) || price <= 0) return;
        const key = keyFor(item.date, intraday);
        if (!byKey.has(key)) byKey.set(key, { date: intraday ? `${key}:00` : key });
        byKey.get(key)[symbol] = price;  // last bar of that day/hour wins
      });
    });

    return Array.from(byKey.keys()).sort().map(key => {
      const point = byKey.get(key);
      symbols.forEach(symbol => {
        if (point[symbol] === undefined) point[symbol] = null;
      });
      return point;
    });
  }, [chartData]);

  if (Object.keys(chartData).length === 0) {
    return (
      <div className="chart-container" style={{ height: '400px', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <p style={{ color: 'var(--text-secondary)' }}>No chart data available</p>
      </div>
    );
  }

  const CustomTooltip = ({ active, payload, label }) => {
    if (active && payload && payload.length) {
      const date = new Date(label).toLocaleDateString('en-IN', {
        day: 'numeric',
        month: 'short',
        year: 'numeric'
      });

      return (
        <div className="custom-tooltip">
          <div className="tooltip-date">{date}</div>
          {payload.map((entry, index) => (
            <div key={index} className="tooltip-price" style={{ color: entry.color }}>
              {entry.name}: {entry.value?.toFixed(2)}
            </div>
          ))}
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
    <div className="chart-container" style={{ height: '400px' }}>
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={combinedData} margin={{ top: 10, right: 30, left: 20, bottom: 10 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#2a2e36" vertical={false} />
          
          <XAxis
            dataKey="date"
            tickFormatter={formatXAxis}
            tick={{ fill: '#9ca3af', fontSize: 12 }}
            axisLine={{ stroke: '#2a2e36' }}
            tickLine={{ stroke: '#2a2e36' }}
          />
          
          <YAxis
            tickFormatter={(v) => v.toFixed(0)}
            tick={{ fill: '#9ca3af', fontSize: 12 }}
            axisLine={{ stroke: '#2a2e36' }}
            tickLine={{ stroke: '#2a2e36' }}
          />
          
          <Tooltip content={<CustomTooltip />} />
          <Legend wrapperStyle={{ color: '#9ca3af', paddingTop: '20px' }} />
          
          {Object.keys(chartData).map((symbol, index) => (
            <Line
              key={symbol}
              type="monotone"
              dataKey={symbol}
              stroke={colors[index % colors.length]}
              strokeWidth={2}
              dot={false}
              activeDot={{ r: 6 }}
              connectNulls
            />
          ))}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

export default CompareChart;