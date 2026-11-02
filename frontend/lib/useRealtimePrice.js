'use client';

import { useEffect, useRef, useState } from 'react';
import { API_BASE_URL } from './api';

// Ported from the Vite app's hooks/useRealtimePrice.js with the same fixes:
// - every socket handler checks `isCurrent`, so a late event from the old
//   symbol's socket can't overwrite the new symbol's price or status;
// - polling reads a ref, not stale state, so it stops once the socket is up;
// - fallback/demo prices from the backend are never copied over real ones.
export default function useRealtimePrice(symbol, initialPrice, initialChange) {
  const [price, setPrice] = useState(initialPrice);
  const [change, setChange] = useState(initialChange);
  const [connected, setConnected] = useState(false);
  const connectedRef = useRef(false);

  useEffect(() => {
    setPrice(initialPrice);
    setChange(initialChange);
  }, [symbol, initialPrice, initialChange]);

  useEffect(() => {
    if (!symbol) return undefined;
    let isCurrent = true;
    let ws = null;
    let reconnectTimeout = null;
    let attempts = 0;

    const setLive = (value) => {
      if (!isCurrent) return;
      connectedRef.current = value;
      setConnected(value);
    };

    const wsUrl = API_BASE_URL.replace(/^https:/, 'wss:').replace(/^http:/, 'ws:') + '/ws';

    const connect = () => {
      if (!isCurrent) return;
      try {
        ws = new WebSocket(wsUrl);
      } catch {
        return;
      }
      ws.onopen = () => {
        if (!isCurrent) return;
        setLive(true);
        attempts = 0;
        ws.send(JSON.stringify({ type: 'subscribe', symbol }));
      };
      ws.onmessage = (event) => {
        if (!isCurrent) return;
        try {
          const data = JSON.parse(event.data);
          if (data.type === 'price_update' && data.symbol === symbol) {
            setPrice(data.price);
            setChange(data.change);
          }
        } catch {
          // ignore malformed frames
        }
      };
      ws.onerror = () => setLive(false);
      ws.onclose = () => {
        if (!isCurrent) return;
        setLive(false);
        if (attempts < 5) {
          attempts += 1;
          const delay = Math.min(1000 * 2 ** attempts, 30000);
          reconnectTimeout = setTimeout(() => isCurrent && connect(), delay);
        }
      };
    };

    connect();

    const poll = setInterval(async () => {
      if (!isCurrent || connectedRef.current) return;
      try {
        const res = await fetch(`${API_BASE_URL}/api/stock/${encodeURIComponent(symbol)}`);
        if (!res.ok || !isCurrent) return;
        const data = await res.json();
        if (!isCurrent || data.is_fallback_data || typeof data.current_price !== 'number') return;
        setPrice(data.current_price);
        setChange(data.change_percent);
      } catch {
        // keep the last good price
      }
    }, 15000);

    return () => {
      isCurrent = false;
      if (ws) {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: 'unsubscribe', symbol }));
        }
        ws.close();
      }
      clearTimeout(reconnectTimeout);
      clearInterval(poll);
      connectedRef.current = false;
      setConnected(false);
    };
  }, [symbol]);

  return { price, change, connected };
}