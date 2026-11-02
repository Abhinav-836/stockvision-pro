import { toNum } from './format';

// Plain-language observations computed from the numbers on the page.
// Each one states what the data shows and lets the reader judge it,
// instead of a single buy/sell-style verdict.
// tone: 'up' | 'down' | 'neutral'
export function buildSignals(stock) {
  if (!stock) return [];
  const t = stock.technical_indicators || {};
  const price = toNum(stock.current_price);
  const sma50 = toNum(t.sma_50);
  const sma200 = toNum(t.sma_200);
  const rsi = toNum(t.rsi);
  const macd = toNum(t.macd);
  const signal = toNum(t.signal);
  const high = toNum(stock.fifty_two_week_high);
  const low = toNum(stock.fifty_two_week_low);

  const out = [];

  if (price !== null && sma200 !== null && sma200 > 0) {
    const pct = ((price - sma200) / sma200) * 100;
    out.push({
      tone: pct >= 0 ? 'up' : 'down',
      text: `Trading ${Math.abs(pct).toFixed(1)}% ${pct >= 0 ? 'above' : 'below'} its 200-day average.`,
    });
  }

  if (sma50 !== null && sma200 !== null) {
    out.push(
      sma50 >= sma200
        ? { tone: 'up', text: '50-day average is above the 200-day average (longer-term uptrend).' }
        : { tone: 'down', text: '50-day average is below the 200-day average (longer-term downtrend).' }
    );
  }

  if (macd !== null && signal !== null) {
    out.push(
      macd >= signal
        ? { tone: 'up', text: `MACD (${macd.toFixed(2)}) is above its signal line (${signal.toFixed(2)}): momentum is strengthening.` }
        : { tone: 'down', text: `MACD (${macd.toFixed(2)}) is below its signal line (${signal.toFixed(2)}): momentum is weakening.` }
    );
  }

  if (rsi !== null) {
    if (rsi >= 70) out.push({ tone: 'down', text: `RSI ${rsi.toFixed(1)} is in the overbought zone (above 70).` });
    else if (rsi <= 30) out.push({ tone: 'up', text: `RSI ${rsi.toFixed(1)} is in the oversold zone (below 30).` });
    else out.push({ tone: 'neutral', text: `RSI ${rsi.toFixed(1)} is in the neutral 30–70 range.` });
  }

  if (price !== null && high !== null && low !== null && high > low) {
    const fromHigh = ((high - price) / high) * 100;
    out.push({
      tone: 'neutral',
      text:
        fromHigh <= 1
          ? 'Trading at or near its 52-week high.'
          : `${fromHigh.toFixed(1)}% below its 52-week high.`,
    });
  }

  return out;
}

// Position of the price inside its 52-week range, 0–100, or null.
export function rangePosition(stock) {
  const price = toNum(stock?.current_price);
  const high = toNum(stock?.fifty_two_week_high);
  const low = toNum(stock?.fifty_two_week_low);
  if (price === null || high === null || low === null || high <= low) return null;
  return Math.min(100, Math.max(0, ((price - low) / (high - low)) * 100));
}