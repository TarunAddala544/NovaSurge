import { useEffect, useState, useRef } from "react";

const PHASE_LABELS = {
  DETECTING: "DETECTED",
  RECOVERING: "RECOVERED",
  GUARDRAIL: "GUARDRAIL",
};

const PHASE_COLORS = {
  DETECTED:  "bg-red-600 text-white",
  RECOVERED: "bg-emerald-600 text-white",
  GUARDRAIL: "bg-amber-500 text-black",
};

export default function ReasoningFeed({ streamData }) {
  const [logs, setLogs] = useState([]);
  const lastTextRef = useRef(null);
  const idRef = useRef(0);

  useEffect(() => {
    if (!streamData || !streamData.reasoning) return;
    if (lastTextRef.current === streamData.reasoning) return;
    lastTextRef.current = streamData.reasoning;

    const rawPhase = streamData?.round_status?.phase || "DETECTING";
    // Map WS phase → display label
    const phase =
      PHASE_LABELS[rawPhase] ??
      (rawPhase === "RECOVERING" ? "RECOVERED" : "DETECTED");

    const newEntry = {
      id: idRef.current++,
      text: streamData.reasoning,
      service: streamData?.anomaly?.affected_service || "system",
      phase,
      timestamp: new Date().toLocaleTimeString("en-US", { hour12: false }),
    };

    setLogs((prev) => [newEntry, ...prev].slice(0, 6));
  }, [streamData]);

  return (
    <div className="h-full flex flex-col font-mono text-sm text-slate-200 overflow-hidden">
      {logs.length === 0 && (
        <div className="flex-1 flex items-center justify-center text-slate-500 text-xs">
          Waiting for reasoning events…
        </div>
      )}

      <div className="flex flex-col gap-2 overflow-hidden">
        {logs.map((log) => (
          <div
            key={log.id}
            className="reasoning-entry p-3 rounded-lg bg-slate-900 border border-slate-700 animate-fadeIn"
          >
            <div className="flex items-center gap-2 mb-1 flex-wrap">
              <span className="timestamp text-slate-500 text-xs">
                [{log.timestamp}]
              </span>

              <span
                className={`phase-badge px-2 py-0.5 text-xs font-bold rounded ${
                  PHASE_COLORS[log.phase] || "bg-slate-600 text-white"
                } ${log.phase}`}
              >
                {log.phase}
              </span>

              <span className="service-badge px-2 py-0.5 text-xs rounded bg-blue-700 text-white font-semibold">
                {log.service}
              </span>
            </div>

            <p className="reasoning-text text-slate-200 leading-snug text-sm">
              {log.text}
            </p>
          </div>
        ))}
      </div>
    </div>
  );
}