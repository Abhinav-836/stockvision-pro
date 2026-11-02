'use client';

import Link from 'next/link';
import { displaySymbol, stockPath } from '@/lib/format';
import { useWatchlist } from '@/lib/watchlist';

export default function WatchlistView() {
  const { list, remove } = useWatchlist();

  return (
    <div className="stack">
      <div>
        <h1 className="h1">Watchlist</h1>
        <p className="muted">Saved in this browser only.</p>
      </div>

      {list.length === 0 ? (
        <div className="panel empty">
          <p>Nothing saved yet.</p>
          <p className="muted small">Open any stock and choose &ldquo;Add to watchlist&rdquo;.</p>
          <Link className="btn" href="/">
            Find a stock
          </Link>
        </div>
      ) : (
        <>
          <ul className="panel list">
            {list.map((s) => (
              <li key={s} className="list-row">
                <Link href={stockPath(s)} className="list-main">
                  <span className="ticker-sm">{displaySymbol(s)}</span>
                  {s.endsWith('.NS') && <span className="muted small">NSE</span>}
                  {s.endsWith('.BO') && <span className="muted small">BSE</span>}
                </Link>
                <button className="btn btn-sm btn-ghost" onClick={() => remove(s)} aria-label={`Remove ${s} from watchlist`}>
                  Remove
                </button>
              </li>
            ))}
          </ul>
          {list.length >= 2 && list.length <= 5 && (
            <Link className="btn btn-ghost" href={`/compare?s=${encodeURIComponent(list.join(','))}`}>
              Compare all {list.length}
            </Link>
          )}
        </>
      )}
    </div>
  );
}