'use client';

import { useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import CompareChart, { SERIES_COLORS } from './CompareChart';
import { compareStocks, getStockChartData } from '@/lib/api';
import { normalizeBars } from '@/lib/bars';
import {
  currencyFor,
  directionClass,
  displaySymbol,
  fmtCompact,
  fmtNumber,
  fmtPercent,
  fmtPrice,
  stockPath,
  toNum,
} from '@/lib/format';
import useSlowFlag from '@/lib/useSlowFlag';

const PERIODS = [
  { value: '1mo', label: '1M' },
  { value: '3mo', label: '3M' },
  { value: '6mo', label: '6M' },
  { value: '1y', label: '1Y' },
];

function parseSymbols(text) {
  return [...new Set(String(text || '').toUpperCase().split(/[\s,]+/).map((s) => s.replace(/[^A-Z0-9.&^=-]/g, '')).filter(Boolean))];
}

// Which column wins each row. Returns the index of the best stock or -1.
function bestIndex(stocks, pick, rule) {
  let best = -1;
  let bestVal = null;
  let tied = false;
  stocks.forEach((s, i) => {
    const v = toNum(pick(s));
    if (v === null) return;
    if (rule === 'low-positive' && v <= 0) return;
    if (v === bestVal) {
      tied = true;
      return;
    }
    const better = bestVal === null || (rule === 'high' ? v > bestVal : v < bestVal);
    if (better) {
      best = i;
      bestVal = v;
      tied = false;
    }
  });
  // No highlight for a single stock or a tie for first place.
  return stocks.length > 1 && !tied ? best : -1;
}

const ROWS = [
  { label: 'Price', render: (s) => fmtPrice(s.current_price, currencyFor(s)) },
  { label: 'Change today', render: (s) => fmtPercent(s.change_percent, { sign: true }), dir: (s) => s.change_percent },
  { label: 'Market cap', render: (s) => fmtCompact(s.market_cap, currencyFor(s)) },
  { label: 'P/E', render: (s) => fmtNumber(s.pe_ratio), pick: (s) => s.pe_ratio, rule: 'low-positive' },
  { label: 'ROE', render: (s) => fmtPercent(s.roe), pick: (s) => s.roe, rule: 'high' },
  { label: 'Dividend yield', render: (s) => fmtPercent(s.dividend_yield), pick: (s) => s.dividend_yield, rule: 'high' },
  { label: 'Debt / equity', render: (s) => fmtNumber(s.debt_to_equity), pick: (s) => s.debt_to_equity, rule: 'low' },
  { label: 'Model score', render: (s) => (toNum(s.ai_score) === null ? '—' : Math.round(s.ai_score)), pick: (s) => s.ai_score, rule: 'high' },
];

export default function CompareView() {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const symbols = useMemo(() => parseSymbols(params.get('s')), [params]);

  const [input, setInput] = useState(symbols.join(', '));
  const [formError, setFormError] = useState('');
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [period, setPeriod] = useState('3mo');
  const [charts, setCharts] = useState({});
  const [chartLoading, setChartLoading] = useState(false);
  const slow = useSlowFlag(loading, 5000);

  const ready = symbols.length >= 2;
  const key = symbols.join(',');

  useEffect(() => {
    setInput(symbols.join(', '));
  }, [key]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!ready) {
      setData(null);
      return undefined;
    }
    let cancelled = false;
    setLoading(true);
    setError('');
    setData(null);
    compareStocks(symbols)
      .then((d) => !cancelled && setData(d))
      .catch((e) => !cancelled && setError(e.message || 'Comparison failed.'))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [key, ready]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!ready) return undefined;
    let cancelled = false;
    setChartLoading(true);
    Promise.all(symbols.map((s) => getStockChartData(s, period).catch(() => []))).then((results) => {
      if (cancelled) return;
      const next = {};
      symbols.forEach((s, i) => {
        next[s] = results[i];
      });
      setCharts(next);
      setChartLoading(false);
    });
    return () => {
      cancelled = true;
    };
  }, [key, ready, period]); // eslint-disable-line react-hooks/exhaustive-deps

  const series = useMemo(
    () =>
      symbols
        .map((s) => {
          const bars = normalizeBars(charts[s], false);
          if (bars.length < 2) return null;
          const base = bars[0].value;
          return {
            symbol: s,
            label: displaySymbol(s),
            points: bars.map((b) => ({ time: b.time, value: (b.value / base - 1) * 100 })),
          };
        })
        .filter(Boolean),
    [charts, key] // eslint-disable-line react-hooks/exhaustive-deps
  );

  const submit = (e) => {
    e.preventDefault();
    const list = parseSymbols(input);
    if (list.length < 2) return setFormError('Enter at least 2 symbols.');
    if (list.length > 5) return setFormError('You can compare up to 5 stocks.');
    setFormError('');
    router.replace(`${pathname}?s=${encodeURIComponent(list.join(','))}`);
  };

  const stocks = data?.stocks || [];
  const ai = data?.ai_analysis;

  return (
    <div className="stack">
      <div>
        <h1 className="h1">Compare stocks</h1>
        <p className="muted">Up to 5 symbols, US or Indian. Separate them with commas.</p>
      </div>

      <form className="search search-lg" onSubmit={submit}>
        <label htmlFor="compare-input" className="sr-only">
          Symbols to compare
        </label>
        <input
          id="compare-input"
          value={input}
          onChange={(e) => setInput(e.target.value.toUpperCase())}
          placeholder="AAPL, MSFT, RELIANCE.NS"
          autoComplete="off"
          spellCheck={false}
        />
        <button className="btn" type="submit" disabled={loading}>
          Compare
        </button>
      </form>
      {formError && <p className="text-down small">{formError}</p>}

      {!ready && symbols.length === 1 && (
        <p className="muted">Add at least one more symbol to compare with {displaySymbol(symbols[0])}.</p>
      )}

      {slow && loading && (
        <div className="notice" role="status">
          Waking up the data server. It sleeps when idle, so the first load can take up to a minute.
        </div>
      )}

      {error && (
        <div className="notice notice-warn" role="alert">
          {error}
        </div>
      )}

      {ready && (
        <section className="panel">
          <div className="panel-bar">
            <h2 className="panel-title flush">Performance</h2>
            <div className="seg" role="group" aria-label="Chart period">
              {PERIODS.map((p) => (
                <button key={p.value} className={period === p.value ? 'on' : ''} onClick={() => setPeriod(p.value)} aria-pressed={period === p.value}>
                  {p.label}
                </button>
              ))}
            </div>
          </div>
          {chartLoading ? (
            <div className="sk" style={{ height: 380 }} />
          ) : series.length ? (
            <>
              <ul className="legend">
                {series.map((s, i) => {
                  const last = s.points[s.points.length - 1].value;
                  return (
                    <li key={s.symbol}>
                      <span className="swatch" style={{ background: `var(${SERIES_COLORS[i % SERIES_COLORS.length]})` }} />
                      <span className="legend-name">{s.label}</span>
                      <span className={`num ${directionClass(last)}`}>{fmtPercent(last, { sign: true, digits: 1 })}</span>
                    </li>
                  );
                })}
              </ul>
              <CompareChart series={series} />
              <p className="muted small note">Percentage change from the first day of the period, so stocks of any price or currency compare fairly.</p>
            </>
          ) : (
            <div className="chart-empty muted">No price history available for this period.</div>
          )}
        </section>
      )}

      {loading && <div className="panel"><div className="sk" style={{ height: 300 }} /></div>}

      {stocks.length > 0 && (
        <section className="panel">
          <h2 className="panel-title">Key numbers</h2>
          {Array.isArray(data.failed_symbols) && data.failed_symbols.length > 0 && (
            <div className="notice small">
              Live data unavailable for {data.failed_symbols.join(', ')}. Showing last known or estimated values.
            </div>
          )}
          <div className="table-scroll">
            <table className="table">
              <thead>
                <tr>
                  <th scope="col" />
                  {stocks.map((s) => (
                    <th key={s.symbol} scope="col" className="num">
                      <Link href={stockPath(s.original_symbol || s.symbol)}>{displaySymbol(s.symbol)}</Link>
                      <div className="th-sub">{s.company_name}</div>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {ROWS.map((row) => {
                  const best = row.pick ? bestIndex(stocks, row.pick, row.rule) : -1;
                  return (
                    <tr key={row.label}>
                      <th scope="row">{row.label}</th>
                      {stocks.map((s, i) => (
                        <td key={s.symbol} className={`num ${row.dir ? directionClass(row.dir(s)) : ''} ${i === best ? 'best' : ''}`}>
                          {row.render(s)}
                        </td>
                      ))}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <p className="muted small note">
            Highlighted: best in the row (lowest positive P/E and debt, highest ROE, yield and score).
          </p>
        </section>
      )}

      {ai && ai.is_fallback && stocks.length > 0 && (
        <p className="muted small">The AI summary is unavailable right now. Try again in a minute.</p>
      )}

      {ai && !ai.is_fallback && (ai.analysis || ai.risk_assessment) && (
        <section className="panel">
          <h2 className="panel-title">Summary</h2>
          <dl className="tags">
            {[
              ['Growth', ai.best_for_growth],
              ['Value', ai.best_for_value],
              ['Income', ai.best_for_income],
              ['Lowest risk', ai.safest_option],
            ]
              .filter(([, v]) => v)
              .map(([k, v]) => (
                <div key={k}>
                  <dt>{k}</dt>
                  <dd>{v}</dd>
                </div>
              ))}
          </dl>
          {ai.analysis && <p className="prose">{ai.analysis}</p>}
          {ai.risk_assessment && (
            <>
              <h3 className="h3">Risks</h3>
              <p className="prose">{ai.risk_assessment}</p>
            </>
          )}
          <p className="muted small note">Written by an AI model from the numbers above. It can be wrong; check the data before relying on it.</p>
        </section>
      )}
    </div>
  );
}