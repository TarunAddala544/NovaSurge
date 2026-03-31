import { useEffect, useRef, useState, useCallback } from "react";
import { MOCK_STREAM } from "../constants/mockData";

const WS_URL = "ws://172.20.66.195:8000/ws/stream";
const RECONNECT_MS = 3000;
const BUFFER_SIZE = 60;
const MOCK_INTERVAL_MS = 2000;

export default function useNovaSurgeStream() {
  const [streamData, setStreamData] = useState(null);
  const [connected, setConnected] = useState(false);
  const [lastUpdate, setLastUpdate] = useState(null);
  const [buffer, setBuffer] = useState([]);

  const wsRef = useRef(null);
  const reconnectTimer = useRef(null);
  const mockTimer = useRef(null);
  const isConnected = useRef(false);

  const pushToBuffer = useCallback((msg) => {
    setBuffer((prev) => {
      const next = [...prev, msg];
      return next.slice(-BUFFER_SIZE);
    });
    setStreamData(msg);
    setLastUpdate(new Date());
  }, []);

  const stopMock = useCallback(() => {
    if (mockTimer.current) {
      clearInterval(mockTimer.current);
      mockTimer.current = null;
    }
  }, []);

  const startMock = useCallback(() => {
    if (mockTimer.current) return; // already running
    mockTimer.current = setInterval(() => {
      if (!isConnected.current) {
        pushToBuffer(MOCK_STREAM());
      }
    }, MOCK_INTERVAL_MS);
  }, [pushToBuffer]);

  const connect = useCallback(() => {
    try {
      const ws = new WebSocket(WS_URL);
      wsRef.current = ws;

      ws.onopen = () => {
        console.log("✅ WebSocket connected to backend");
        isConnected.current = true;
        setConnected(true);
        stopMock(); // stop mock when real WS comes up
      };

      ws.onmessage = (event) => {
        try {
          const parsed = JSON.parse(event.data);
          pushToBuffer(parsed);
        } catch (e) {
          console.warn("Failed to parse WebSocket message", e);
        }
      };

      ws.onclose = () => {
        console.log("❌ WebSocket disconnected. Retrying in 3s...");
        isConnected.current = false;
        setConnected(false);
        startMock(); // fall back to mock
        reconnectTimer.current = setTimeout(connect, RECONNECT_MS);
      };

      ws.onerror = () => {
        ws.close();
      };
    } catch (err) {
      console.warn("WebSocket error:", err);
      isConnected.current = false;
      setConnected(false);
      startMock();
      reconnectTimer.current = setTimeout(connect, RECONNECT_MS);
    }
  }, [pushToBuffer, startMock, stopMock]);

  useEffect(() => {
    // Start with mock immediately so something shows
    startMock();
    // Attempt WebSocket connection
    connect();

    return () => {
      stopMock();
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
      if (wsRef.current) wsRef.current.close();
    };
  }, [connect, startMock, stopMock]);

  return { streamData, connected, lastUpdate, buffer };
}