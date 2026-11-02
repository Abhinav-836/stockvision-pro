import StockView from '@/components/StockView';
import { displaySymbol } from '@/lib/format';

function readSymbol(raw) {
  let s = String(raw || '');
  try {
    s = decodeURIComponent(s);
  } catch {
    // keep the raw value
  }
  return s.toUpperCase().trim();
}

export async function generateMetadata({ params }) {
  const { symbol } = await params;
  const s = readSymbol(symbol);
  return { title: `${displaySymbol(s)} price, chart and fundamentals` };
}

export default async function StockPage({ params }) {
  const { symbol } = await params;
  const s = readSymbol(symbol);
  // key resets all state when navigating from one stock to another
  return <StockView key={s} symbol={s} />;
}