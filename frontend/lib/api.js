// Client for the FastAPI backend on Render.
// Same endpoints and behaviour as the old Vite api.jsx: 1-minute in-memory
// cache, retries only on network errors / timeouts / 5xx, FastAPI error
// details flattened into readable messages.

export const API_BASE_URL = (process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000').replace(/\/$/, '');

const CACHE_DURATION = 60 * 1000;
const REQUEST_TIMEOUT = 30 * 1000;
const cache = new Map();

function getCached(key) {
  const hit = cache.get(key);
  if (hit && Date.now() - hit.timestamp < CACHE_DURATION) return hit.data;
  if (hit) cache.delete(key);
  return null;
}

function setCached(key, data) {
  cache.set(key, { data, timestamp: Date.now() });
}

async function fetchAPI(endpoint, options = {}) {
  const { timeout = REQUEST_TIMEOUT, ...fetchOptions } = options;
  const url = endpoint.startsWith('http')
    ? endpoint
    : `${API_BASE_URL}${endpoint.startsWith('/') ? endpoint : `/${endpoint}`}`;

  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeout);

  try {
    const response = await fetch(url, {
      ...fetchOptions,
      signal: controller.signal,
      headers: { 'Content-Type': 'application/json', ...fetchOptions.headers },
    });

    if (!response.ok) {
      let message = `HTTP ${response.status}`;
      try {
        const body = await response.json();
        const detail = body.detail;
        if (Array.isArray(detail)) {
          message = detail.map((d) => d.msg || String(d)).join('; ');
        } else {
          message = detail || body.error || body.message || message;
        }
      } catch {
        message = response.statusText || message;
      }
      const error = new Error(message);
      error.status = response.status;
      throw error;
    }

    return await response.json();
  } catch (error) {
    if (error.name === 'AbortError') {
      throw new Error('The data server took too long to respond.');
    }
    if (error instanceof TypeError) {
      throw new Error('Could not reach the data server. Check your connection and try again.');
    }
    throw error;
  } finally {
    clearTimeout(timeoutId);
  }
}

// 4xx responses (bad symbol, rate limit) fail identically on retry, so only
// network errors, timeouts and 5xx are retried.
async function fetchWithRetry(endpoint, options = {}, retries = 3) {
  for (let attempt = 0; attempt < retries; attempt++) {
    try {
      return await fetchAPI(endpoint, options);
    } catch (error) {
      const retryable = error.status === undefined || error.status >= 500;
      if (!retryable || attempt === retries - 1) throw error;
      await new Promise((r) => setTimeout(r, 1000 * 2 ** attempt));
    }
  }
}

export function cleanSymbol(symbol) {
  return String(symbol || '').toUpperCase().trim();
}

export async function getMarketIndices() {
  const cached = getCached('market-indices');
  if (cached) return cached;
  try {
    const data = await fetchWithRetry('/api/market-indices?use_cache=true');
    const list = Array.isArray(data) ? data : Array.isArray(data?.data) ? data.data : [];
    setCached('market-indices', list);
    return list;
  } catch {
    return [];
  }
}

export async function getStockAnalysis(symbol) {
  const s = cleanSymbol(symbol);
  if (!s) throw new Error('Enter a stock symbol.');
  const key = `stock:${s}`;
  const cached = getCached(key);
  if (cached) return cached;
  const data = await fetchWithRetry(`/api/stock/${encodeURIComponent(s)}?use_cache=true`);
  setCached(key, data);
  return data;
}

export async function getStockChartData(symbol, period = '1mo') {
  const s = cleanSymbol(symbol);
  if (!s) return [];
  const key = `chart:${s}:${period}`;
  const cached = getCached(key);
  if (cached) return cached;
  const data = await fetchWithRetry(
    `/api/stock/${encodeURIComponent(s)}/chart?period=${period}&use_cache=true`
  );
  const bars = Array.isArray(data) ? data : [];
  setCached(key, bars);
  return bars;
}

function cleanList(symbols) {
  const clean = symbols.map(cleanSymbol).filter(Boolean);
  if (clean.length < 2) throw new Error('Enter at least 2 symbols.');
  if (new Set(clean).size !== clean.length) throw new Error('Each symbol can only appear once.');
  // Sorted copy for the cache key only, so columns keep the typed order.
  return { clean, key: [...clean].sort().join(',') };
}

// Numbers only (no AI), from /api/compare. Fast, so the table and chart
// can show while the AI summary is still being written.
export async function compareStocks(symbols) {
  const { clean, key } = cleanList(symbols);
  const cacheKey = `compare:${key}`;
  const cached = getCached(cacheKey);
  if (cached) return cached;

  const data = await fetchWithRetry('/api/compare', {
    method: 'POST',
    body: JSON.stringify({ symbols: clean }),
  });
  setCached(cacheKey, data);
  return data;
}

// AI summary from /api/ai/compare. The model can be slow or rate-limited
// and the server retries and tries backup models, so this gets 75s and is
// not retried by the browser. Returns the ai_analysis object (with
// is_fallback: true when no model answered).
export async function getAIComparison(symbols) {
  const { clean, key } = cleanList(symbols);
  const cacheKey = `ai-compare:${key}`;
  const cached = getCached(cacheKey);
  if (cached) return cached;

  const data = await fetchAPI('/api/ai/compare', {
    method: 'POST',
    body: JSON.stringify({ symbols: clean }),
    timeout: 75 * 1000,
  });
  if (data && data.success === false) throw new Error(data.error || 'AI summary failed.');
  const ai = data?.ai_analysis || null;
  // Only real AI answers are cached; a fallback should be retried next time.
  if (ai && !ai.is_fallback) setCached(cacheKey, ai);
  return ai;
}

// Render's free tier sleeps when idle. Pinging /health as soon as the site
// opens starts the wake-up while the visitor is still typing a symbol.
let warmupPromise = null;
export function wakeUpBackend() {
  if (!warmupPromise) {
    warmupPromise = fetch(`${API_BASE_URL}/health`, { signal: AbortSignal.timeout(60000) })
      .then((r) => r.ok)
      .catch(() => false);
  }
  return warmupPromise;
}