'use client';

import { useEffect, useRef, useState } from 'react';
import { cssVar, useTheme } from '@/lib/theme';
import { fmtNumber } from '@/lib/format';

function formatTime(time, intraday) {
  if (typeof time === 'string') {
    const d = new Date(`${time}T00:00:00Z`);
    return d.toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' });
  }
  const d = new Date(time * 1000);
  return d.toLocaleString('en-IN', {
    day: 'numeric',
    month: 'short',
    hour: intraday ? '2-digit' : undefined,
    minute: intraday ? '2-digit' : undefined,
    timeZone: 'UTC',
  });
}

// mode: 'line' | 'candles'
export default function PriceChart({ bars, mode = 'line', currency = '$', intraday = false, height = 360 }) {
  const containerRef = useRef(null);
  const { theme } = useTheme();
  const [hover, setHover] = useState(null);

  useEffect(() => {
    const el = containerRef.current;
    if (!el || !bars.length) return undefined;
    let chart = null;
    let cancelled = false;

    import('lightweight-charts').then(({ createChart, LineSeries, CandlestickSeries, ColorType, CrosshairMode, LineStyle }) => {
      if (cancelled) return;
      const text = cssVar('--text-3');
      const grid = cssVar('--grid');
      const border = cssVar('--border');
      const up = cssVar('--up');
      const down = cssVar('--down');
      const isUp = bars[bars.length - 1].value >= bars[0].value;

      chart = createChart(el, {
        autoSize: true,
        layout: {
          background: { type: ColorType.Solid, color: 'transparent' },
          textColor: text,
          fontFamily: getComputedStyle(document.body).fontFamily,
          fontSize: 11,
        },
        grid: { vertLines: { visible: false }, horzLines: { color: grid } },
        rightPriceScale: { borderVisible: false, scaleMargins: { top: 0.08, bottom: 0.08 } },
        timeScale: { borderColor: border, timeVisible: intraday, secondsVisible: false, fixLeftEdge: true, fixRightEdge: true },
        crosshair: {
          mode: CrosshairMode.Magnet,
          vertLine: { color: text, style: LineStyle.Dashed, labelBackgroundColor: cssVar('--text-2') },
          horzLine: { color: text, style: LineStyle.Dashed, labelBackgroundColor: cssVar('--text-2') },
        },
        localization: { priceFormatter: (p) => `${currency}${fmtNumber(p, 2)}` },
        handleScroll: false,
        handleScale: false,
      });

      let series;
      if (mode === 'candles') {
        series = chart.addSeries(CandlestickSeries, {
          upColor: up,
          downColor: down,
          borderUpColor: up,
          borderDownColor: down,
          wickUpColor: up,
          wickDownColor: down,
          priceLineVisible: false,
        });
        series.setData(bars.map(({ time, open, high, low, close }) => ({ time, open, high, low, close })));
      } else {
        series = chart.addSeries(LineSeries, {
          color: isUp ? up : down,
          lineWidth: 2,
          priceLineVisible: false,
          crosshairMarkerRadius: 4,
        });
        series.setData(bars.map(({ time, value }) => ({ time, value })));
      }
      chart.timeScale().fitContent();

      chart.subscribeCrosshairMove((param) => {
        if (!param.time || !param.seriesData.size) {
          setHover(null);
          return;
        }
        const d = param.seriesData.get(series);
        if (!d) return;
        setHover({ time: param.time, value: d.value ?? d.close, ohlc: d.open !== undefined ? d : null });
      });
    });

    return () => {
      cancelled = true;
      if (chart) chart.remove();
      setHover(null);
    };
  }, [bars, mode, currency, intraday, theme]);

  const last = bars[bars.length - 1];
  const shown = hover || (last ? { time: last.time, value: last.value, ohlc: mode === 'candles' ? last : null } : null);

  return (
    <div className="chart">
      {shown && (
        <div className="chart-readout num" aria-live="off">
          <span className="muted">{formatTime(shown.time, intraday)}</span>
          {shown.ohlc ? (
            <span>
              O {fmtNumber(shown.ohlc.open)} · H {fmtNumber(shown.ohlc.high)} · L {fmtNumber(shown.ohlc.low)} · C{' '}
              {fmtNumber(shown.ohlc.close)}
            </span>
          ) : (
            <span>
              {currency}
              {fmtNumber(shown.value)}
            </span>
          )}
        </div>
      )}
      <div ref={containerRef} className="chart-canvas" style={{ height }} />
    </div>
  );
}