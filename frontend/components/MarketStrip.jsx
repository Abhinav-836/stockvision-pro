'use client';

import { useEffect, useState } from 'react';
import { getMarketIndices } from '@/lib/api';
import { directionClass, fmtNumber, fmtPercent } from '@/lib/format';

// Fixed-height strip: it reserves its space while loading so the page
// doesn't jump when the indices arrive.
export default function MarketStrip() {
  const [indices, setIndices] = useState(null);

  useEffect(() => {
    let alive = true;
    const load = () => getMarketIndices().then((d) => alive && setIndices(d));
    load();
    const id = setInterval(load, 5 * 60 * 1000);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);

  if (indices && indices.length === 0) return <div className="strip" aria-hidden="true" />;

  return (
    <div className="strip" aria-label="Market indices">
      <div className="wrap strip-row">
        {indices === null
          ? Array.from({ length: 6 }, (_, i) => <div key={i} className="sk strip-sk" />)
          : indices.map((ix) => (
              <div key={ix.symbol || ix.name} className="strip-item">
                <span className="strip-name">{ix.name}</span>
                <span className="num">{fmtNumber(ix.value)}</span>
                <span className={`num ${directionClass(ix.change)}`}>{fmtPercent(ix.change, { sign: true })}</span>
              </div>
            ))}
      </div>
    </div>
  );
}