import { toNum } from './format';

// The backend's sources format the same trading day differently
// (yFinance "2026-10-01T00:00:00-04:00", NSE "...+05:30" or no offset,
// Alpha Vantage "2026-10-01"). For daily bars the calendar day is taken
// straight from the string so no timezone conversion can shift it. For
// intraday bars the timestamp is moved into the exchange's own clock,
// because the chart library renders times as UTC.
function intradayTime(dateStr) {
  const ms = Date.parse(dateStr);
  if (Number.isNaN(ms)) return null;
  const m = /([+-])(\d{2}):?(\d{2})$/.exec(dateStr);
  const offsetSec = m ? (m[1] === '-' ? -1 : 1) * (Number(m[2]) * 3600 + Number(m[3]) * 60) : 0;
  return Math.floor(ms / 1000) + offsetSec;
}

export function isIntradayPeriod(period) {
  return period === '1d' || period === '5d';
}

// Returns ascending, de-duplicated bars:
// { time, value, open, high, low, close }
export function normalizeBars(raw, intraday) {
  if (!Array.isArray(raw)) return [];
  const byTime = new Map();
  for (const item of raw) {
    const dateStr = item?.date ?? item?.time;
    if (dateStr === undefined || dateStr === null) continue;
    const close = toNum(item.price ?? item.close ?? item.value);
    if (close === null || close <= 0) continue;

    let time;
    if (typeof dateStr === 'number') {
      time = dateStr > 1e12 ? Math.floor(dateStr / 1000) : dateStr;
      if (!intraday) time = new Date(time * 1000).toISOString().slice(0, 10);
    } else {
      time = intraday ? intradayTime(String(dateStr)) : String(dateStr).slice(0, 10);
    }
    if (time === null || time === undefined) continue;

    const open = toNum(item.open) ?? close;
    const high = Math.max(toNum(item.high) ?? close, open, close);
    const low = Math.min(toNum(item.low) ?? close, open, close);
    byTime.set(time, { time, value: close, open, high, low, close });
  }
  return [...byTime.values()].sort((a, b) => (a.time < b.time ? -1 : a.time > b.time ? 1 : 0));
}

export function periodChange(bars) {
  if (!bars.length) return null;
  const first = bars[0].value;
  const last = bars[bars.length - 1].value;
  if (!first) return null;
  return { abs: last - first, pct: ((last - first) / first) * 100 };
}