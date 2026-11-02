import Link from 'next/link';
import SymbolSearch from '@/components/SymbolSearch';
import { IN_POPULAR, US_POPULAR } from '@/lib/symbols';
import { displaySymbol, stockPath } from '@/lib/format';

function SymbolList({ title, items }) {
  return (
    <section className="panel">
      <h2 className="panel-title">{title}</h2>
      <ul className="list">
        {items.map(([symbol, name]) => (
          <li key={symbol}>
            <Link href={stockPath(symbol)} className="list-row list-link">
              <span className="ticker-sm">{displaySymbol(symbol)}</span>
              <span className="muted">{name}</span>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}

export default function Home() {
  return (
    <div className="stack">
      <section className="intro">
        <h1 className="h1">Look up a stock</h1>
        <p className="muted">
          Price history, fundamentals and technical indicators for US and Indian (NSE) stocks.
        </p>
        <SymbolSearch size="lg" />
      </section>
      <div className="grid-2">
        <SymbolList title="United States" items={US_POPULAR} />
        <SymbolList title="India (NSE)" items={IN_POPULAR} />
      </div>
    </div>
  );
}