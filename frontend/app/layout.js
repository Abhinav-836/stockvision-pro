import { GeistSans } from 'geist/font/sans';
import { GeistMono } from 'geist/font/mono';
import { Analytics } from '@vercel/analytics/next';
import { SpeedInsights } from '@vercel/speed-insights/next';
import SiteHeader from '@/components/SiteHeader';
import MarketStrip from '@/components/MarketStrip';
import { themeInitScript } from '@/lib/theme-script';
import './globals.css';

export const metadata = {
  title: {
    default: 'StockVision Pro: US and Indian stock data',
    template: '%s · StockVision Pro',
  },
  description:
    'Prices, charts, fundamentals and technical indicators for US and NSE stocks, with side-by-side comparison.',
};

export const viewport = {
  themeColor: [
    { media: '(prefers-color-scheme: light)', color: '#fafaf9' },
    { media: '(prefers-color-scheme: dark)', color: '#0f1012' },
  ],
};

export default function RootLayout({ children }) {
  return (
    <html lang="en" className={`${GeistSans.variable} ${GeistMono.variable}`} suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeInitScript }} />
      </head>
      <body>
        <a href="#main" className="skip">
          Skip to content
        </a>
        <SiteHeader />
        <MarketStrip />
        <main id="main" className="wrap main">
          {children}
        </main>
        <footer className="site-footer">
          <div className="wrap footer-row">
            <span>
              © {new Date().getFullYear()} StockVision Pro · Built by{' '}
              <a href="https://github.com/Abhinav-836" style={{ color: 'inherit', textDecoration: 'underline', textUnderlineOffset: 3 }}>
                Abhinav Ashutosh
              </a>
            </span>
            <span>
              Data from NSE, Finnhub, Alpha Vantage and Yahoo Finance; may be delayed. For information only, not
              investment advice.
            </span>
          </div>
        </footer>
        <Analytics />
        <SpeedInsights />
      </body>
    </html>
  );
}