'use client';

import { useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import PriceChart from './PriceChart';
import { getStockAnalysis, getStockChartData } from '@/lib/api';
import { isIntradayPeriod, normalizeBars, periodChange } from '@/lib/bars';
import {
  currencyFor,
  directionClass,
  displaySymbol,
  fmtCompact,
  fmtNumber,
  fmtPercent,
  fmtPrice,
  toNum,
} from '@/lib/format';
import { buildSignals, rangePosition } from '@/lib/signals';
import useRealtimePrice from '@/lib/useRealtimePrice';
import useSlowFlag from '@/lib/useSlowFlag';
import { useWatchlist } from '@/lib/watchlist';

const PERIODS = [
  { value: '1d', label: '1D' },
  { value: '5d', label: '5D' },
  { value: '1mo', label: '1M' },
  { value: '3mo', label: '3M' },
  { value: '6mo', label: '6M' },
  { value: '1y', label: '1Y' },
];

function Row({ label, value, hint }) {
  return (
    <div className="kv-row">
      <dt>
        {label}
        {hint && <span className="kv-hint">{hint}</span>}
      </dt>
      <dd className="num">{value}</dd>
    </div>
  );
}

function Skeleton() {
  return (
    <div className="stack" aria-hidden="true">
      <div className="quote-head">
        <div>
          <div className="sk" style={{ width: 140, height: 28 }} />
          <div className="sk" style={{ width: 220, height: 14, marginTop: 10 }} />
        </div>
        <div className="sk" style={{ width: 160, height: 36 }} />
      </div>
      <div className="panel">
        <div className="sk" style={{ height: 360 }} />
      </div>
      <div className="grid-2">
        <div className="panel"><div className="sk" style={{ height: 260 }} /></div>
        <div className="panel"><div className="sk" style={{ height: 260 }} /></div>
      </div>
    </div>
  );
}

export default function StockView({ symbol }) {
  const watchlist = useWatchlist();
  const [stock, setStock] = useState(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [reloadKey, setReloadKey] = useState(0);

  const [period, setPeriod] = useState('1mo');
  const [mode, setMode] = useState('line');
  const [rawBars, setRawBars] = useState([]);
  const [chartLoading, setChartLoading] = useState(true);
  const [chartError, setChartError] = useState('');

  // For Indian stocks the backend returns symbol "RELIANCE" and
  // original_symbol "RELIANCE.NS"; every data call must use the latter.
  const dataSymbol = stock ? stock.original_symbol || stock.symbol : symbol;
  const slow = useSlowFlag(loading, 5000);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError('');
    setStock(null);
    getStockAnalysis(symbol)
      .then((data) => !cancelled && setStock(data))
      .catch((err) => !cancelled && setError(err.message || 'Could not load this stock.'))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [symbol, reloadKey]);

  useEffect(() => {
    let cancelled = false;
    setChartLoading(true);
    setChartError('');
    getStockChartData(dataSymbol, period)
      .then((data) => !cancelled && setRawBars(data))
      .catch(() => {
        if (cancelled) return;
        setRawBars([]);
        setChartError('Price history is unavailable right now.');
      })
      .finally(() => !cancelled && setChartLoading(false));
    return () => {
      cancelled = true;
    };
  }, [dataSymbol, period, reloadKey]);

  const intraday = isIntradayPeriod(period);
  const bars = useMemo(() => normalizeBars(rawBars, intraday), [rawBars, intraday]);
  const change = periodChange(bars);

  const live = useRealtimePrice(stock ? dataSymbol : null, stock?.current_price, stock?.change_percent);
  const price = live.price ?? stock?.current_price;
  const dayChange = live.change ?? stock?.change_percent;

  if (error) {
    return (
      <div className="panel empty">
        <h1 className="h2">Couldn&rsquo;t load {symbol}</h1>
        <p className="muted">{error}</p>
        <p className="muted small">
          Check the symbol. Indian stocks need an exchange suffix, for example <code>RELIANCE.NS</code>.
        </p>
        <div className="row gap-s">
          <button className="btn" onClick={() => setReloadKey((k) => k + 1)}>
            Try again
          </button>
          <Link className="btn btn-ghost" href="/">
            Search another symbol
          </Link>
        </div>
      </div>
    );
  }

  if (loading || !stock) {
    return (
      <>
        {slow && (
          <div className="notice" role="status">
            Waking up the data server. It sleeps when idle, so the first load can take up to a minute.
          </div>
        )}
        <Skeleton />
      </>
    );
  }

  const currency = currencyFor(stock);
  const t = stock.technical_indicators || {};
  const signals = buildSignals({ ...stock, current_price: price });
  const pos = rangePosition({ ...stock, current_price: price });
  const inList = watchlist.has(dataSymbol);
  const g = stock.growth_metrics || {};
  const volatility = toNum(stock.volatility);

  return (
    <div className="stack">
      {stock.is_stale && (
        <div className="notice">Live data is temporarily unavailable. Showing the last known real price.</div>
      )}
      {stock.is_fallback_data && (
        <div className="notice notice-warn">
          {stock.message || 'Live data is unavailable. These are estimated values, not real market data.'}
        </div>
      )}

      <header className="quote-head">
        <div>
          <div className="row gap-s baseline">
            <h1 className="ticker">{displaySymbol(stock.symbol)}</h1>
            <span className="company">{stock.company_name || ''}</span>
          </div>
          <p className="meta">
            {[stock.exchange, stock.sector, stock.is_indian_stock ? 'NSE/BSE' : null].filter(Boolean).join(' · ')}
          </p>
        </div>
        <div className="quote-price">
          <div className="price num">{fmtPrice(price, currency)}</div>
          <div className="row gap-s end">
            <span className={`chg ${directionClass(dayChange)}`}>
              <span className="num">{fmtPercent(dayChange, { sign: true })}</span> today
            </span>
            <span className={`live ${live.connected ? 'on' : ''}`} title={live.connected ? 'Streaming live prices' : 'Prices refresh every 15 seconds'}>
              {live.connected ? 'Live' : 'Delayed'}
            </span>
          </div>
        </div>
      </header>

      <div className="row gap-s">
        <button className={`btn btn-sm ${inList ? 'btn-on' : 'btn-ghost'}`} onClick={() => watchlist.toggle(dataSymbol)} aria-pressed={inList}>
          {inList ? '★ In watchlist' : '☆ Add to watchlist'}
        </button>
        <Link className="btn btn-sm btn-ghost" href={`/compare?s=${encodeURIComponent(dataSymbol)}`}>
          Compare with…
        </Link>
      </div>

      <section className="panel">
        <div className="panel-bar">
          <div className="seg" role="group" aria-label="Chart period">
            {PERIODS.map((p) => (
              <button key={p.value} className={period === p.value ? 'on' : ''} onClick={() => setPeriod(p.value)} aria-pressed={period === p.value}>
                {p.label}
              </button>
            ))}
          </div>
          <div className="row gap-m">
            {change && !chartLoading && (
              <span className={`num small ${directionClass(change.pct)}`}>
                {fmtPercent(change.pct, { sign: true })} over {PERIODS.find((p) => p.value === period)?.label}
              </span>
            )}
            <div className="seg" role="group" aria-label="Chart type">
              <button className={mode === 'line' ? 'on' : ''} onClick={() => setMode('line')} aria-pressed={mode === 'line'}>
                Line
              </button>
              <button className={mode === 'candles' ? 'on' : ''} onClick={() => setMode('candles')} aria-pressed={mode === 'candles'}>
                Candles
              </button>
            </div>
          </div>
        </div>
        {chartLoading ? (
          <div className="sk" style={{ height: 392 }} />
        ) : bars.length ? (
          <PriceChart bars={bars} mode={mode} currency={currency} intraday={intraday} />
        ) : (
          <div className="chart-empty muted">{chartError || 'No price history for this period.'}</div>
        )}
      </section>

      <div className="grid-2">
        <section className="panel">
          <h2 className="panel-title">Fundamentals</h2>
          <dl className="kv">
            <Row label="Market cap" value={fmtCompact(stock.market_cap, currency)} />
            <Row label="P/E" value={fmtNumber(stock.pe_ratio)} />
            <Row label="P/B" value={fmtNumber(stock.pb_ratio)} />
            <Row label="EPS" value={fmtPrice(stock.eps, currency)} />
            <Row label="ROE" value={fmtPercent(stock.roe)} />
            <Row label="Dividend yield" value={fmtPercent(stock.dividend_yield)} />
            <Row label="Debt / equity" value={fmtNumber(stock.debt_to_equity)} />
            <Row label="Revenue growth" value={fmtPercent(g.revenue_growth, { digits: 1, sign: true })} />
            <Row label="Earnings growth" value={fmtPercent(g.earnings_growth, { digits: 1, sign: true })} />
            <Row label="Quarterly earnings growth" value={fmtPercent(g.earnings_quarterly_growth, { digits: 1, sign: true })} />
          </dl>
        </section>

        <section className="panel">
          <h2 className="panel-title">Trading</h2>
          {pos !== null && (
            <div className="range">
              <div className="range-labels num small">
                <span>{fmtPrice(stock.fifty_two_week_low, currency)}</span>
                <span className="muted range-name">52-week range</span>
                <span>{fmtPrice(stock.fifty_two_week_high, currency)}</span>
              </div>
              <div className="range-track">
                <div className="range-dot" style={{ left: `${pos}%` }} />
              </div>
            </div>
          )}
          <dl className="kv">
            <Row label="Volume" value={fmtCompact(stock.volume)} />
            <Row label="Avg volume" value={fmtCompact(stock.average_volume)} />
            <Row label="Volatility" hint="annualized" value={volatility === null ? '—' : `${(volatility * 100).toFixed(1)}%`} />
            <Row label="RSI" hint="14-day" value={fmtNumber(t.rsi)} />
            <Row label="SMA 20" value={fmtPrice(t.sma_20, currency)} />
            <Row label="SMA 50" value={fmtPrice(t.sma_50, currency)} />
            <Row label="SMA 200" value={fmtPrice(t.sma_200, currency)} />
            <Row
              label="MACD"
              hint="/ signal"
              value={toNum(t.macd) === null ? '—' : `${fmtNumber(t.macd)}${toNum(t.signal) === null ? '' : ` / ${fmtNumber(t.signal)}`}`}
            />
          </dl>
        </section>
      </div>

      {signals.length > 0 && (
        <section className="panel">
          <h2 className="panel-title">What the numbers show</h2>
          <ul className="signals">
            {signals.map((s) => (
              <li key={s.text} className={`sig-${s.tone}`}>
                {s.text}
              </li>
            ))}
          </ul>
        </section>
      )}

      {toNum(stock.ai_score) !== null && (
        <section className="panel">
          <div className="panel-bar">
            <h2 className="panel-title flush">Model score</h2>
            <span className="num score">
              {Math.round(stock.ai_score)}
              <span className="muted">/100</span>
            </span>
          </div>
          <dl className="tags">
            {stock.valuation && (
              <div>
                <dt>Valuation</dt>
                <dd>{stock.valuation}</dd>
              </div>
            )}
            {stock.growth_potential && (
              <div>
                <dt>Growth</dt>
                <dd>{stock.growth_potential}</dd>
              </div>
            )}
            {stock.risk_level && (
              <div>
                <dt>Risk</dt>
                <dd>{stock.risk_level}</dd>
              </div>
            )}
          </dl>
          <p className="muted small">
            Rule-based score from valuation, profitability, financial health, income, volatility and technicals. It is a
            summary of the data above, not a recommendation to buy or sell.
          </p>
        </section>
      )}
    </div>
  );
}