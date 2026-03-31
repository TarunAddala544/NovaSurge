import useNovaSurgeStream from "./hooks/useNovaSurgeStream";
import ReasoningFeed      from "./components/ReasoningFeed";
import HealthGrid         from "./components/HealthGrid";
import AnomalyScoreChart  from "./components/AnomalyScoreChart";
import LSTMPredictionChart from "./components/LSTMPredictionChart";
import DependencyGraph    from "./components/DependencyGraph";
import DecisionTraceTable from "./components/DecisionTraceTable";

function PanelTitle({ children }) {
  return (
    <h2 className="text-xs font-bold uppercase tracking-widest text-slate-500 mb-1 shrink-0">
      {children}
    </h2>
  );
}

function Panel({ children, className = "" }) {
  return (
    <div
      className={`bg-[#1e293b] rounded-xl border border-slate-700/60 p-3 flex flex-col overflow-hidden ${className}`}
    >
      {children}
    </div>
  );
}

export default function App() {
  const { streamData, connected, lastUpdate, buffer } = useNovaSurgeStream();

  return (
    <div
      className="bg-[#0f172a] text-white w-screen h-screen overflow-hidden flex flex-col"
      style={{ fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace" }}
    >
      {/* ── HEADER ─────────────────────────────────────────── */}
      <header className="shrink-0 px-4 py-2 flex items-center justify-between border-b border-slate-800">
        <div className="flex items-center gap-3">
          <span className="text-base font-extrabold tracking-tight text-white">
            🌪 NovaSurge
          </span>
          <span className="text-xs text-slate-500">
            Autonomous Chaos Engineering &amp; Self-Healing Platform
          </span>
        </div>
        <div className="flex items-center gap-3 text-xs">
          <span
            className={`flex items-center gap-1 font-semibold ${
              connected ? "text-emerald-400" : "text-red-400"
            }`}
          >
            <span
              className={`inline-block w-2 h-2 rounded-full ${
                connected
                  ? "bg-emerald-400 animate-pulse"
                  : "bg-red-400"
              }`}
            />
            {connected ? "LIVE" : "MOCK"}
          </span>
          {lastUpdate && (
            <span className="text-slate-600">
              {lastUpdate.toLocaleTimeString("en-US", { hour12: false })}
            </span>
          )}
          {streamData?.round_status && (
            <span className="text-slate-500">
              Round {streamData.round_status.round} ·{" "}
              <span className="text-amber-400">{streamData.round_status.phase}</span>
            </span>
          )}
        </div>
      </header>

      {/* ── MAIN GRID ──────────────────────────────────────── */}
      {/*
        Top row:    [Anomaly Chart 30%] [Reasoning Feed 40%] [Health Grid 28%]
        Bottom row: [Decision Table 45%] [Dependency Graph 30%] [LSTM 23%]
        Each row is 47% height (leaving breathing room for header)
      */}
      <main className="flex-1 min-h-0 p-2 grid grid-cols-12 grid-rows-2 gap-2">

        {/* ── ROW 1 ── */}

        {/* Panel 2: Anomaly Score Chart — 30% ≈ col-span-4 */}
        <Panel className="col-span-4 row-span-1">
          <PanelTitle>Anomaly Score</PanelTitle>
          <div className="flex-1 min-h-0">
            <AnomalyScoreChart buffer={buffer} />
          </div>
        </Panel>

        {/* Panel 1: Autonomous Reasoning Feed — 40% ≈ col-span-5 — MOST PROMINENT */}
        <Panel className="col-span-5 row-span-1 border-blue-900/60 bg-[#0f172a]">
          <PanelTitle>
            <span className="text-blue-400 text-sm font-black normal-case tracking-normal">
              ⚡ Autonomous Reasoning Engine
            </span>
          </PanelTitle>
          <div className="flex-1 min-h-0 overflow-hidden">
            <ReasoningFeed streamData={streamData} />
          </div>
        </Panel>

        {/* Panel 3: System Health Grid — 28% ≈ col-span-3 */}
        <Panel className="col-span-3 row-span-1">
          <PanelTitle>System Health</PanelTitle>
          <div className="flex-1 min-h-0 overflow-auto">
            <HealthGrid streamData={streamData} />
          </div>
        </Panel>

        {/* ── ROW 2 ── */}

        {/* Panel 4: Decision Trace Table — 45% ≈ col-span-6 */}
        <Panel className="col-span-6 row-span-1">
          <PanelTitle>Decision Trace</PanelTitle>
          <div className="flex-1 min-h-0 overflow-hidden">
            <DecisionTraceTable streamData={streamData} />
          </div>
        </Panel>

        {/* Panel 5: Dependency Graph — 30% ≈ col-span-4 */}
        <Panel className="col-span-4 row-span-1">
          <PanelTitle>Service Dependency Graph</PanelTitle>
          <div className="flex-1 min-h-0 overflow-hidden">
            <DependencyGraph streamData={streamData} />
          </div>
        </Panel>

        {/* Panel 6: LSTM Prediction Horizon — 23% ≈ col-span-2 */}
        <Panel className="col-span-2 row-span-1">
          <div className="flex-1 min-h-0 overflow-hidden">
            <LSTMPredictionChart buffer={buffer} streamData={streamData} />
          </div>
        </Panel>

      </main>
    </div>
  );
}
