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

  const combinedData = useMemo(() => {
    const symbols = Object.keys(chartData);
    if (symbols.length === 0) return [];

    // Get all dates from all charts
    const allDates = new Set();
    symbols.forEach(symbol => {
      chartData[symbol]?.forEach(item => {
        if (item?.date) allDates.add(item.date);
      });
    });

    // Create combined dataset
    return Array.from(allDates).sort().map(date => {
      const point = { date };
      symbols.forEach(symbol => {
        const dataPoint = chartData[symbol]?.find(d => d.date === date);
        point[symbol] = dataPoint?.price || null;
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
              {entry.name}: ${entry.value?.toFixed(2)}
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
            tickFormatter={(v) => `$${v.toFixed(0)}`}
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
            />
          ))}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

export default CompareChart;