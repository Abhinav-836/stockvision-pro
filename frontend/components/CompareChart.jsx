'use client';

import { useEffect, useRef } from 'react';
import { cssVar, useTheme } from '@/lib/theme';

export const SERIES_COLORS = ['--s1', '--s2', '--s3', '--s4', '--s5'];

// series: [{ symbol, label, points: [{ time, value }] }] where value is the
// % change since the first bar. Prices in different currencies and sizes
// (AAPL at $340, RELIANCE at ₹1,400) are only comparable this way.
export default function CompareChart({ series, height = 340 }) {
  const ref = useRef(null);
  const { theme } = useTheme();

  useEffect(() => {
    const el = ref.current;
    if (!el || !series.length) return undefined;
    let chart = null;
    let cancelled = false;

    import('lightweight-charts').then(({ createChart, LineSeries, ColorType, CrosshairMode, LineStyle }) => {
      if (cancelled) return;
      const text = cssVar('--text-3');
      chart = createChart(el, {
        autoSize: true,
        layout: {
          background: { type: ColorType.Solid, color: 'transparent' },
          textColor: text,
          fontFamily: getComputedStyle(document.body).fontFamily,
          fontSize: 11,
        },
        grid: { vertLines: { visible: false }, horzLines: { color: cssVar('--grid') } },
        rightPriceScale: { borderVisible: false },
        timeScale: { borderColor: cssVar('--border'), fixLeftEdge: true, fixRightEdge: true },
        crosshair: {
          mode: CrosshairMode.Normal,
          vertLine: { color: text, style: LineStyle.Dashed, labelBackgroundColor: cssVar('--text-2') },
          horzLine: { color: text, style: LineStyle.Dashed, labelBackgroundColor: cssVar('--text-2') },
        },
        localization: { priceFormatter: (p) => `${p > 0 ? '+' : ''}${p.toFixed(1)}%` },
        handleScroll: false,
        handleScale: false,
      });

      let first = null;
      series.forEach((s, i) => {
        const line = chart.addSeries(LineSeries, {
          color: cssVar(SERIES_COLORS[i % SERIES_COLORS.length]),
          lineWidth: 2,
          priceLineVisible: false,
        });
        line.setData(s.points);
        if (!first) first = line;
      });

      // Baseline at 0% so above/below the starting point reads at a glance.
      first?.createPriceLine({ price: 0, color: cssVar('--border-strong'), lineWidth: 1, lineStyle: LineStyle.Solid, axisLabelVisible: false });
      chart.timeScale().fitContent();
    });

    return () => {
      cancelled = true;
      if (chart) chart.remove();
    };
  }, [series, theme]);

  return <div ref={ref} className="chart-canvas" style={{ height }} />;
}