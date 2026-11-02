export const isNum = (v) => typeof v === 'number' && Number.isFinite(v);

export const toNum = (v) => {
  if (v === null || v === undefined || v === '') return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
};

export const currencyFor = (stock) => (stock?.is_indian_stock ? '₹' : '$');

const DASH = '—';

export function fmtNumber(v, digits = 2) {
  const n = toNum(v);
  if (n === null) return DASH;
  return n.toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export function fmtPrice(v, currency = '$') {
  const n = toNum(v);
  if (n === null) return DASH;
  return `${currency}${fmtNumber(n, 2)}`;
}

export function fmtPercent(v, { digits = 2, sign = false } = {}) {
  const n = toNum(v);
  if (n === null) return DASH;
  const prefix = sign && n > 0 ? '+' : '';
  return `${prefix}${n.toFixed(digits)}%`;
}

export function fmtCompact(v, currency = '') {
  const n = toNum(v);
  if (n === null || n === 0) return DASH;
  const abs = Math.abs(n);
  if (abs >= 1e12) return `${currency}${(n / 1e12).toFixed(2)}T`;
  if (abs >= 1e9) return `${currency}${(n / 1e9).toFixed(2)}B`;
  if (abs >= 1e6) return `${currency}${(n / 1e6).toFixed(2)}M`;
  if (abs >= 1e3) return `${currency}${(n / 1e3).toFixed(1)}K`;
  return `${currency}${n.toFixed(0)}`;
}

export function directionClass(v) {
  const n = toNum(v);
  if (n === null || n === 0) return '';
  return n > 0 ? 'up' : 'down';
}

export function displaySymbol(symbol) {
  return String(symbol || '').replace(/\.(NS|BO)$/, '');
}

export function stockPath(symbol) {
  return `/stock/${encodeURIComponent(String(symbol).toUpperCase())}`;
}