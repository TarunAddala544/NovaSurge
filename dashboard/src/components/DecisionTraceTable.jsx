import { useState, useEffect, useRef } from "react";
import { MOCK_ROUNDS } from "../constants/mockData";

const ROUNDS_POLL_MS = 10000;

function recoveryColor(secs) {
  if (secs === null || secs === undefined) return "text-slate-400";
  if (secs < 30)  return "text-emerald-400 font-bold";
  if (secs <= 60) return "text-amber-400 font-bold";
  return "text-red-400 font-bold";
}

function rowBorderClass(status) {
  switch (status) {
    case "COMPLETE":   return "border-l-4 border-emerald-500";
    case "RECOVERING": return "border-l-4 border-amber-400 animate-pulse";
    case "FAILED":     return "border-l-4 border-red-500";
    default:           return "border-l-4 border-slate-600";
  }
}

function statusPill(status) {
  switch (status) {
    case "COMPLETE":   return "bg-emerald-700 text-white";
    case "RECOVERING": return "bg-amber-500 text-black";
    case "FAILED":     return "bg-red-600 text-white";
    default:           return "bg-slate-600 text-white";
  }
}

export default function DecisionTraceTable({ streamData }) {
  const [rows, setRows] = useState(MOCK_ROUNDS);
  const seenRounds = useRef(new Set(MOCK_ROUNDS.map((r) => r.round)));

  // Live round_status update from WebSocket
  useEffect(() => {
    if (!streamData?.round_status) return;
    const rs = streamData.round_status;
    if (!rs.current_round) return;

    setRows((prev) => {
      const existing = prev.find((r) => r.round === rs.current_round);
      const updated = {
        round: rs.current_round,
        failure_type: rs.failure_type || "—",
        service: streamData?.anomaly?.affected_service || "—",
        if_score: streamData?.anomaly?.iforest_score ?? null,
        decision:
          rs.phase === "RECOVERING"
            ? "hpa-scaleout"
            : rs.phase === "DETECTING"
            ? "analyzing"
            : "—",
        remediator:
          rs.phase === "RECOVERING" ? "HPARemediator" : "—",
        recovery_s:
          rs.phase === "IDLE" ? rs.elapsed_seconds : null,
        rca_origin: "CPU limit exhaustion",
        status:
          rs.phase === "IDLE"
            ? "COMPLETE"
            : rs.phase === "RECOVERING"
            ? "RECOVERING"
            : "DETECTING",
      };

      if (existing) {
        return prev.map((r) =>
          r.round === rs.current_round ? updated : r
        );
      } else {
        seenRounds.current.add(rs.current_round);
        return [updated, ...prev].slice(0, 20);
      }
    });
  }, [streamData]);

  // Poll GET /rounds every 10 seconds
  useEffect(() => {
    async function fetchRounds() {
      try {
        const res = await fetch("http://localhost:8000/rounds");
        if (!res.ok) return;
        const data = await res.json();
        if (!Array.isArray(data)) return;
        setRows(data.slice().reverse());
      } catch {
        // backend not up — use mock/WS data
      }
    }

    fetchRounds();
    const timer = setInterval(fetchRounds, ROUNDS_POLL_MS);
    return () => clearInterval(timer);
  }, []);

  const cols = [
    { key: "round",        label: "Round" },
    { key: "failure_type", label: "Failure Type" },
    { key: "service",      label: "Service" },
    { key: "if_score",     label: "IF Score" },
    { key: "decision",     label: "Decision" },
    { key: "remediator",   label: "Remediator" },
    { key: "recovery_s",   label: "Recovery(s)" },
    { key: "rca_origin",   label: "RCA Origin" },
    { key: "status",       label: "Status" },
  ];

  return (
    <div className="h-full flex flex-col overflow-hidden">
      <div className="flex-1 overflow-auto">
        <table className="w-full text-[11px] border-collapse min-w-[540px]">
          <thead className="sticky top-0 z-10">
            <tr className="bg-slate-800 text-slate-400">
              {cols.map((c) => (
                <th
                  key={c.key}
                  className="px-2 py-1.5 text-left font-semibold whitespace-nowrap border-b border-slate-700"
                >
                  {c.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => (
              <tr
                key={`${row.round}-${i}`}
                className={`${rowBorderClass(row.status)} bg-slate-900 hover:bg-slate-800 transition-colors`}
              >
                <td className="px-2 py-1.5 text-slate-200 font-mono">{row.round}</td>
                <td className="px-2 py-1.5 text-slate-300 whitespace-nowrap">{row.failure_type}</td>
                <td className="px-2 py-1.5 text-blue-300 whitespace-nowrap">{row.service}</td>
                <td className="px-2 py-1.5 font-mono text-amber-300">
                  {row.if_score !== null && row.if_score !== undefined
                    ? row.if_score.toFixed(2)
                    : "—"}
                </td>
                <td className="px-2 py-1.5 text-slate-300 whitespace-nowrap">{row.decision}</td>
                <td className="px-2 py-1.5 text-slate-400 whitespace-nowrap">{row.remediator}</td>
                <td className={`px-2 py-1.5 font-mono ${recoveryColor(row.recovery_s)}`}>
                  {row.recovery_s !== null && row.recovery_s !== undefined
                    ? `${row.recovery_s}s`
                    : "—"}
                </td>
                <td className="px-2 py-1.5 text-slate-400 whitespace-nowrap max-w-[120px] truncate">
                  {row.rca_origin}
                </td>
                <td className="px-2 py-1.5">
                  <span
                    className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${statusPill(row.status)}`}
                  >
                    {row.status}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}