import { useEffect, useState, useRef } from "react";

export default function ReasoningFeed({ data }) {
  const [logs, setLogs] = useState([]);
  const lastTextRef = useRef(null);
  const idRef = useRef(0);

  useEffect(() => {
    if (!data || !data.reasoning) return;

    // ✅ Prevent duplicate logs
    if (lastTextRef.current === data.reasoning) return;
    lastTextRef.current = data.reasoning;

    const newLog = {
      id: idRef.current++,
      text: data.reasoning,
      service: data?.anomaly?.affected_service || "system",
      phase: data?.round_status?.phase || "UNKNOWN",
      timestamp: new Date().toLocaleTimeString()
    };

    // eslint-disable-next-line react-hooks/set-state-in-effect
    setLogs((prevLogs) => {
      const updated = [newLog, ...prevLogs];
      return updated.slice(0, 6);
    });

  }, [data]);

  const getPhaseColor = (phase) => {
    if (phase === "DETECTING") return "bg-red-500";
    if (phase === "RECOVERING") return "bg-green-500";
    return "bg-yellow-500";
  };

  return (
    <div className="h-full flex flex-col text-sm font-mono text-slate-200 overflow-hidden">
      
      {/* <div className="font-bold mb-2 text-lg">Reasoning Feed</div> */}

      <div className="flex-1 overflow-y-auto pr-1">
        {logs.map((log) => (
          <div
            key={log.id}
            className="mb-2 p-2 rounded bg-[#0f172a] border border-slate-700 animate-fadeIn"
          >
            <div className="flex items-center gap-2 mb-1">
              <span className="text-gray-400 text-xs">
                [{log.timestamp}]
              </span>

              <span className={`px-2 py-0.5 text-xs rounded ${getPhaseColor(log.phase)}`}>
                {log.phase}
              </span>

              <span className="px-2 py-0.5 text-xs rounded bg-blue-600">
                {log.service}
              </span>
            </div>

            <div className="text-slate-300">
              {log.text}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}