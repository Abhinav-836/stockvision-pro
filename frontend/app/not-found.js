import Link from 'next/link';

export default function NotFound() {
  return (
    <div className="panel empty">
      <h1 className="h2">Page not found</h1>
      <p className="muted">That page doesn&rsquo;t exist. Search for a stock instead.</p>
      <Link className="btn" href="/">
        Go to search
      </Link>
    </div>
  );
}