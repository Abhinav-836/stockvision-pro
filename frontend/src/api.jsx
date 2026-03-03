const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

const CACHE_DURATION = 60 * 1000; // 1 minute
const cache = new Map();

function getCached(key) {
  const cached = cache.get(key);
  if (cached && Date.now() - cached.timestamp < CACHE_DURATION) {
    return cached.data;
  }
  if (cached) cache.delete(key);
  return null;
}

function setCached(key, data) {
  cache.set(key, { data, timestamp: Date.now() });
}

async function fetchWithRetry(url, options = {}, retries = 3) {
  for (let i = 0; i < retries; i++) {
    try {
      return await fetchAPI(url, options);
    } catch (error) {
      if (i === retries - 1) throw error;
      await new Promise(resolve => setTimeout(resolve, 1000 * Math.pow(2, i)));
    }
  }
}

async function fetchAPI(endpoint, options = {}) {
  const url = endpoint.startsWith('http') ? endpoint : `${API_BASE_URL}${endpoint}`;
  
  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 15000);

    const response = await fetch(url, {
      ...options,
      signal: controller.signal,
      headers: {
        'Content-Type': 'application/json',
        ...options.headers
      }
    });

    clearTimeout(timeoutId);

    if (!response.ok) {
      let errorMessage = `HTTP ${response.status}`;
      try {
        const errorData = await response.json();
        errorMessage = errorData.detail || errorData.message || errorMessage;
      } catch {
        errorMessage = response.statusText || errorMessage;
      }
      throw new Error(errorMessage);
    }

    return await response.json();
  } catch (error) {
    if (error.name === 'AbortError') {
      throw new Error('Request timeout - server took too long to respond');
    }
    if (error.message.includes('Failed to fetch')) {
      throw new Error('Cannot connect to server. Please ensure backend is running.');
    }
    throw error;
  }
}

export async function healthCheck() {
  try {
    const response = await fetch(`${API_BASE_URL}/health`);
    return response.ok;
  } catch {
    return false;
  }
}

export async function getMarketIndices(useCache = true) {
  if (useCache) {
    const cached = getCached('market-indices');
    if (cached) return cached;
  }

  try {
    const data = await fetchWithRetry('/api/market-indices?use_cache=' + useCache);
    if (useCache) setCached('market-indices', data);
    return data;
  } catch {
    return [];
  }
}

export async function getStockAnalysis(symbol, useCache = true) {
  if (!symbol?.trim()) throw new Error('Symbol required');
  
  const cleanSymbol = symbol.toUpperCase().trim();
  
  if (useCache) {
    const cached = getCached(`stock:${cleanSymbol}`);
    if (cached) return cached;
  }

  const data = await fetchWithRetry(`/api/stock/${cleanSymbol}?use_cache=${useCache}`);
  if (useCache) setCached(`stock:${cleanSymbol}`, data);
  return data;
}

export async function getStockChartData(symbol, period = '1mo', useCache = true) {
  if (!symbol?.trim()) return [];
  
  const cleanSymbol = symbol.toUpperCase().trim();
  const cacheKey = `chart:${cleanSymbol}:${period}`;
  
  if (useCache) {
    const cached = getCached(cacheKey);
    if (cached) return cached;
  }

  try {
    const data = await fetchWithRetry(`/api/stock/${cleanSymbol}/chart?period=${period}&use_cache=${useCache}`);
    if (useCache) setCached(cacheKey, data);
    return data;
  } catch (error) {
    console.error(`Error fetching chart for ${symbol}:`, error);
    return [];
  }
}

export async function compareStocks(symbols, useCache = true) {
  if (!Array.isArray(symbols) || symbols.length < 2) {
    throw new Error('At least 2 symbols required');
  }

  const cleanSymbols = symbols.map(s => s.toUpperCase().trim()).filter(Boolean);
  
  if (new Set(cleanSymbols).size !== cleanSymbols.length) {
    throw new Error('Duplicate symbols detected');
  }

  const cacheKey = `compare:${cleanSymbols.sort().join(',')}`;
  if (useCache) {
    const cached = getCached(cacheKey);
    if (cached) return cached;
  }

  const data = await fetchWithRetry('/api/ai/compare', {  // Using AI compare endpoint
    method: 'POST',
    body: JSON.stringify({ symbols: cleanSymbols })
  });

  if (useCache) setCached(cacheKey, data);
  return data;
}

export async function getTrendingStocks(useCache = true) {
  if (useCache) {
    const cached = getCached('trending');
    if (cached) return cached;
  }

  try {
    const data = await fetchWithRetry('/api/trending?use_cache=' + useCache);
    if (useCache) setCached('trending', data);
    return data;
  } catch {
    return { trending: [] };
  }
}

export default {
  healthCheck,
  getMarketIndices,
  getStockAnalysis,
  getStockChartData,
  compareStocks,
  getTrendingStocks
};