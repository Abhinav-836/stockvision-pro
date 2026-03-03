import { useState, useEffect } from 'react';

const useRealtimePrice = (symbol, initialPrice, initialChange) => {
  const [price, setPrice] = useState(initialPrice);
  const [change, setChange] = useState(initialChange);
  const [connected, setConnected] = useState(false);

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

    // Get the correct WebSocket URL based on environment
    const getWebSocketUrl = () => {
      // In production, use the Render URL
      if (import.meta.env.PROD) {
        // Replace https with wss for WebSocket
        const apiUrl = import.meta.env.VITE_API_URL || 'https://stockvision-pro-jbve.onrender.com';
        return apiUrl.replace('https://', 'wss://') + '/ws';
      }
      // In development, use localhost
      return 'ws://localhost:8000/ws';
    };

    const connectWebSocket = () => {
      try {
        const wsUrl = getWebSocketUrl();
        console.log('Connecting to WebSocket:', wsUrl);
        
        ws = new WebSocket(wsUrl);

        ws.onopen = () => {
          console.log(`WebSocket connected for ${symbol}`);
          setConnected(true);
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
          setConnected(false);
        };

        ws.onclose = () => {
          console.log('WebSocket disconnected');
          setConnected(false);
          
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

    // Polling fallback (every 10 seconds)
    const pollInterval = setInterval(async () => {
      if (!connected) {
        try {
          // Fallback to REST API if WebSocket fails
          const response = await fetch(`${import.meta.env.VITE_API_URL}/api/stock/${symbol}`);
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
    };
  }, [symbol]);

  // Update when initial values change
  useEffect(() => {
    if (!connected) {
      setPrice(initialPrice);
      setChange(initialChange);
    }
  }, [initialPrice, initialChange, connected]);

  return { price, change, connected };
};

export default useRealtimePrice;
