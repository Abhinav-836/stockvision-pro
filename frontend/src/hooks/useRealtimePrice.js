import { useState, useEffect, useRef } from 'react';
import { API_BASE_URL } from '../api';

const useRealtimePrice = (symbol, initialPrice, initialChange) => {
  const [price, setPrice] = useState(initialPrice);
  const [change, setChange] = useState(initialChange);
  const [connected, setConnected] = useState(false);

  // FIXED: `connected` state was being read inside a setInterval closure
  // created once when the effect ran, so it stayed frozen at its initial
  // value (false) for the interval's whole lifetime — the REST polling
  // fallback kept firing every 10s even after the WebSocket connected
  // successfully. A ref always reflects the latest value inside closures.
  const connectedRef = useRef(false);

  useEffect(() => {
    if (!symbol) {
      setPrice(initialPrice);
      setChange(initialChange);
      return;
    }

    let ws = null;
    let reconnectTimeout = null;
    let reconnectAttempts = 0;
    const maxReconnectAttempts = 5;

    const setConnectedState = (value) => {
      connectedRef.current = value;
      setConnected(value);
    };

    // Get the correct WebSocket URL based on environment.
    // FIXED: now derives from the same API_BASE_URL used everywhere else
    // (api.jsx) instead of re-reading import.meta.env.VITE_API_URL with
    // its own separate (and previously inconsistent) fallback/hardcoded URL.
    const getWebSocketUrl = () => {
      return API_BASE_URL.replace('https://', 'wss://').replace('http://', 'ws://') + '/ws';
    };

    const connectWebSocket = () => {
      try {
        const wsUrl = getWebSocketUrl();
        console.log('Connecting to WebSocket:', wsUrl);

        ws = new WebSocket(wsUrl);

        ws.onopen = () => {
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
          console.error('WebSocket error:', error);
          setConnectedState(false);
        };

        ws.onclose = () => {
          console.log('WebSocket disconnected');
          setConnectedState(false);

          // Attempt to reconnect
          if (reconnectAttempts < maxReconnectAttempts) {
            reconnectAttempts++;
            const delay = Math.min(1000 * Math.pow(2, reconnectAttempts), 30000);
            console.log(`Reconnecting in ${delay}ms (attempt ${reconnectAttempts}/${maxReconnectAttempts})`);

            reconnectTimeout = setTimeout(() => {
              connectWebSocket();
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
      if (!connectedRef.current) {
        try {
          const response = await fetch(`${API_BASE_URL}/api/stock/${symbol}`);
          if (!response.ok) return;
          const data = await response.json();
          setPrice(data.current_price);
          setChange(data.change_percent);
        } catch (error) {
          console.error('Error polling price:', error);
        }
      }
    }, 10000);

    return () => {
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
    };
  }, [symbol]);

  // Update when initial values change (only while WS/poll isn't already
  // supplying live data)
  useEffect(() => {
    if (!connected) {
      setPrice(initialPrice);
      setChange(initialChange);
    }
  }, [initialPrice, initialChange, connected]);

  return { price, change, connected };
};

export default useRealtimePrice;