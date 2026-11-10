import Link from 'next/link';

export const metadata = { title: 'Terms, disclaimer and privacy' };

const CONTACT = 'ashutoshabhinavbachra0009@gmail.com';

export default function Terms() {
  return (
    <article className="panel legal">
      <h1 className="h2">Terms, disclaimer and privacy</h1>
      <p className="muted small">Last updated 10 November 2026</p>

      <div className="prose">
        <h2>Not investment advice</h2>
        <p>
          StockVision Pro is a free educational project built by Abhinav Ashutosh (StrattonTrade). Prices, charts,
          indicators, scores and AI-written comparisons are generated automatically from third-party data and simple
          models. They can be delayed, incomplete or wrong, and nothing here is investment, financial or tax advice or a
          recommendation to buy or sell any security. We are not registered with SEBI or any other regulator as an
          investment adviser or research analyst. Do your own research, or speak to a registered adviser, before
          investing.
        </p>

        <h2>Data</h2>
        <p>
          Market data comes from NSE, Finnhub, Alpha Vantage and Yahoo Finance and belongs to them. It is shown for
          personal, non-commercial use and may be delayed. AI comparisons are written by models reached through
          OpenRouter, which receive only the stock symbols and figures being compared.
        </p>

        <h2>Privacy</h2>
        <ul>
          <li>There are no accounts. Your watchlist and theme are stored only in your browser.</li>
          <li>
            Our server (on Render) sees your IP address and the stocks you look up, as any website does, to answer the
            request and stop abuse. We don&rsquo;t sell this or use it for advertising.
          </li>
          <li>
            Vercel Web Analytics and Speed Insights count visits and page speed without cookies and without storing
            personal information.
          </li>
        </ul>

        <h2>Use of the service</h2>
        <p>
          Don&rsquo;t scrape, overload or resell the service. It is provided free and &ldquo;as is&rdquo;, without any
          guarantee that it will be available or accurate, and to the extent the law allows we are not liable for
          losses from using it, including trading losses. These terms are governed by the laws of India.
        </p>

        <h2>Contact</h2>
        <p>
          <a href={`mailto:${CONTACT}`}>{CONTACT}</a>. If these terms change, the date at the top changes too.
        </p>
        <p>
          <Link href="/">Back to search</Link>
        </p>
      </div>
    </article>
  );
}
