import { useEffect, useRef, useState, useCallback } from 'react';

/**
 * Custom hook to connect to the FastAPI WebSocket endpoint (/ws/monitor).
 * Safely handles reconnects, message dispatching, and connection status.
 */
export function useWebSocketMonitor({ onViolation, onUpdate }) {
  const [isConnected, setIsConnected] = useState(false);
  const wsRef = useRef(null);
  const reconnectTimeoutRef = useRef(null);
  const onViolationRef = useRef(onViolation);
  const onUpdateRef = useRef(onUpdate);

  useEffect(() => {
    onViolationRef.current = onViolation;
  }, [onViolation]);

  useEffect(() => {
    onUpdateRef.current = onUpdate;
  }, [onUpdate]);

  const connect = useCallback(() => {
    // Build websocket URL dynamically
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = window.location.host;
    const wsUrl = `${protocol}//${host}/ws/monitor`;

    try {
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onopen = () => {
        setIsConnected(true);
      };

      ws.onmessage = (event) => {
        try {
          const payload = JSON.parse(event.data);
          if (payload.type === 'violation_confirmed' && onViolationRef.current) {
            onViolationRef.current(payload.data);
          } else if (payload.type === 'monitoring_update' && onUpdateRef.current) {
            onUpdateRef.current(payload.data);
          }
        } catch (err) {
          console.warn('Error parsing WebSocket message:', err);
        }
      };

      ws.onclose = () => {
        setIsConnected(false);
        // Automatic reconnection after 2.5s
        reconnectTimeoutRef.current = setTimeout(connect, 2500);
      };

      ws.onerror = (err) => {
        console.warn('WebSocket connection error:', err);
        ws.close();
      };
    } catch (e) {
      console.warn('Failed to establish WebSocket:', e);
      reconnectTimeoutRef.current = setTimeout(connect, 3000);
    }
  }, []);

  useEffect(() => {
    connect();

    // Ping keepalive every 15s
    const pingInterval = setInterval(() => {
      if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
        wsRef.current.send('ping');
      }
    }, 15000);

    return () => {
      clearInterval(pingInterval);
      if (reconnectTimeoutRef.current) clearTimeout(reconnectTimeoutRef.current);
      if (wsRef.current) wsRef.current.close();
    };
  }, [connect]);

  return { isConnected };
}
