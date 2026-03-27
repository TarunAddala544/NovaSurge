import { useEffect, useState } from "react";
import { MOCK_STREAM } from "../constants/mockData";

export default function useNovaSurgeStream() {
  const [data, setData] = useState(null);
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    let ws;

    function connect() {
      try {
        ws = new WebSocket("ws://localhost:8000/ws/stream");

        ws.onopen = () => {
          console.log("✅ Connected to backend");
          setConnected(true);
        };

        ws.onmessage = (event) => {
          const parsed = JSON.parse(event.data);
          setData(parsed);
        };

        ws.onclose = () => {
          console.log("❌ Disconnected. Retrying...");
          setConnected(false);
          setTimeout(connect, 3000);
        };

        ws.onerror = () => {
          ws.close();
        };

      } catch (error) {
        console.log("WebSocket error:", error);
        setConnected(false);
      }
    }

    connect();

    // ✅ ALWAYS UPDATE MOCK DATA (no blocking)
    const interval = setInterval(() => {
      setData(MOCK_STREAM());
    }, 2000);

    return () => {
      clearInterval(interval);
      if (ws) ws.close();
    };
  }, []); // ❗ run only once

  return { data, connected };
}