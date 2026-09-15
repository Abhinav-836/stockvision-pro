import { useState, useEffect, useRef } from 'react';
import { API_BASE_URL } from '../api';

const useRealtimePrice = (symbol, initialPrice, initialChange) => {
  const [price, setPrice] = useState(initialPrice);
  const [change, setChange] = useState(initialChange);
  const [connected, setConnected] = useState(false);

  // `connected` state was being read inside a setInterval closure created
  // once when the effect ran, so it stayed frozen at its initial value
  // (false) for the interval's whole lifetime — the REST polling fallback
  // kept firing every 10s even after the WebSocket connected successfully.
  // A ref always reflects the latest value inside closures.
  const connectedRef = useRef(false);

  // FIXED: this effect used to gate its reset on `if (!connected)`, but
  // `connected` (React state) went stale during a symbol switch — see the
  // WebSocket effect below for why — so the reset silently no-op'd and the
  // PREVIOUS symbol's last WS-pushed price stayed on screen under the NEW
  // symbol's data until a live tick happened to arrive for it. Resetting
  // unconditionally here removes the dependency on `connected` entirely:
  // any time the symbol changes, or the REST data for the current symbol
  // refreshes, the display syncs to that known-good value immediately. A
  // live WebSocket tick for the currently active symbol (guarded by the
  // onmessage symbol check below) is free to overwrite it again afterward.
  useEffect(() => {
    setPrice(initialPrice);
    setChange(initialChange);
  }, [symbol, initialPrice, initialChange]);

  useEffect(() => {
    // FIXED: root cause of "switching symbols briefly/persistently shows
    // the previous stock's price". Closing a WebSocket is asynchronous —
    // the OLD socket's onopen/onmessage/onclose handlers stay alive in
    // memory until the browser actually fires those events, with no
    // guaranteed ordering versus the NEW socket's onopen. Previously, none
    // of the handlers checked whether they still belonged to the symbol
    // currently being displayed, so a late-arriving event from the OLD
    // connection could still call setConnected/setPrice after the NEW
    // connection had already started — most visibly, the old connection's
    // onclose calling setConnected(false) AFTER the new connection's
    // onopen had already set it true, leaving `connected` stale.
    //
    // `isCurrent` closes that window: every handler checks it before
    // touching state, so once this effect's cleanup runs (symbol changed
    // or component unmounted), nothing from this specific connection can
    // mutate state again, regardless of event ordering.
    let isCurrent = true;

    if (!symbol) {
      return;
    }

    let ws = null;
    let reconnectTimeout = null;
    let reconnectAttempts = 0;
    const maxReconnectAttempts = 5;

    const setConnectedState = (value) => {
      if (!isCurrent) return;
      connectedRef.current = value;
      setConnected(value);
    };

    // Get the correct WebSocket URL based on environment.
    // Derives from the same API_BASE_URL used everywhere else (api.jsx)
    // instead of re-reading import.meta.env.VITE_API_URL with its own
    // separate (and previously inconsistent) fallback/hardcoded URL.
    const getWebSocketUrl = () => {
      return API_BASE_URL.replace('https://', 'wss://').replace('http://', 'ws://') + '/ws';
    };

    const connectWebSocket = () => {
      if (!isCurrent) return;
      try {
        const wsUrl = getWebSocketUrl();
        console.log('Connecting to WebSocket:', wsUrl, 'for', symbol);

        ws = new WebSocket(wsUrl);

        ws.onopen = () => {
          if (!isCurrent) return;
          console.log(`WebSocket connected for ${symbol}`);
          setConnectedState(true);
          reconnectAttempts = 0;

          // Subscribe to symbol
          ws.send(JSON.stringify({
            type: 'subscribe',
            symbol: symbol
          }));
        };

        ws.onmessage = (event) => {
          if (!isCurrent) return;
          try {
            const data = JSON.parse(event.data);
            if (data.type === 'price_update' && data.symbol === symbol) {
              setPrice(data.price);
              setChange(data.change);
            }
          } catch (error) {
            console.error('Error parsing WebSocket message:', error);
          }
        };

        ws.onerror = (error) => {
          if (!isCurrent) return;
          console.error('WebSocket error:', error);
          setConnectedState(false);
        };

        ws.onclose = () => {
          if (!isCurrent) return;
          console.log('WebSocket disconnected');
          setConnectedState(false);

          // Attempt to reconnect
          if (reconnectAttempts < maxReconnectAttempts) {
            reconnectAttempts++;
            const delay = Math.min(1000 * Math.pow(2, reconnectAttempts), 30000);
            console.log(`Reconnecting in ${delay}ms (attempt ${reconnectAttempts}/${maxReconnectAttempts})`);

            reconnectTimeout = setTimeout(() => {
              if (isCurrent) connectWebSocket();
            }, delay);
          }
        };
      } catch (error) {
        console.error('Error creating WebSocket:', error);
      }
    };

    connectWebSocket();

    // Polling fallback (every 10 seconds) — only actually fetches when
    // the WebSocket is genuinely disconnected, thanks to connectedRef.
    const pollInterval = setInterval(async () => {
      if (!isCurrent || connectedRef.current) return;
      try {
        const response = await fetch(`${API_BASE_URL}/api/stock/${symbol}`);
        if (!response.ok || !isCurrent) return;
        const data = await response.json();
        if (!isCurrent) return;
        setPrice(data.current_price);
        setChange(data.change_percent);
      } catch (error) {
        console.error('Error polling price:', error);
      }
    }, 10000);

    return () => {
      isCurrent = false;
      if (ws) {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({
            type: 'unsubscribe',
            symbol: symbol
          }));
        }
        ws.close();
      }
      if (reconnectTimeout) {
        clearTimeout(reconnectTimeout);
      }
      clearInterval(pollInterval);
      connectedRef.current = false;
      // Explicitly reset React's `connected` state on teardown too (not
      // just the ref) — previously this only reset connectedRef, leaving
      // `connected` itself to be corrected solely by the old socket's
      // onclose firing at some later, unpredictable time.
      setConnected(false);
    };
  }, [symbol]);

  return { price, change, connected };
};

export default useRealtimePrice;