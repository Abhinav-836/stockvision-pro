'use client';

import { useEffect } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import SymbolSearch from './SymbolSearch';
import { wakeUpBackend } from '@/lib/api';
import { useTheme } from '@/lib/theme';
import { useWatchlist } from '@/lib/watchlist';

const NAV = [
  { href: '/', label: 'Markets' },
  { href: '/compare', label: 'Compare' },
  { href: '/watchlist', label: 'Watchlist' },
];

function ThemeToggle() {
  const { theme, toggle } = useTheme();
  const next = theme === 'dark' ? 'light' : 'dark';
  return (
    <button className="icon-btn" onClick={toggle} aria-label={`Switch to ${next} theme`} title={`Switch to ${next} theme`}>
      {theme === 'dark' ? (
        <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
          <circle cx="12" cy="12" r="4" />
          <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
        </svg>
      ) : (
        <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
          <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" />
        </svg>
      )}
    </button>
  );
}

export default function SiteHeader() {
  const pathname = usePathname();
  const { list } = useWatchlist();

  // Start waking the Render backend as soon as anyone opens the site.
  useEffect(() => {
    wakeUpBackend();
  }, []);

  const isActive = (href) => (href === '/' ? pathname === '/' || pathname.startsWith('/stock/') : pathname.startsWith(href));

  return (
    <header className="site-header">
      <div className="wrap header-row">
        <Link href="/" className="brand" aria-label="StockVision Pro home">
          <svg viewBox="0 0 20 20" width="18" height="18" aria-hidden="true">
            <path d="M2 15l5-6 4 3 7-9" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          <span>StockVision Pro</span>
        </Link>
        <nav className="nav" aria-label="Main">
          {NAV.map((item) => (
            <Link key={item.href} href={item.href} className={isActive(item.href) ? 'on' : ''} aria-current={isActive(item.href) ? 'page' : undefined}>
              {item.label}
              {item.href === '/watchlist' && list.length > 0 && <span className="count num">{list.length}</span>}
            </Link>
          ))}
        </nav>
        <div className="header-search">
          <SymbolSearch shortcut />
        </div>
        <ThemeToggle />
      </div>
    </header>
  );
}