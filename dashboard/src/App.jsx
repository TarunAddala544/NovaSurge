import useNovaSurgeStream from "./hooks/useNovaSurgeStream";
import ReasoningFeed from "./components/ReasoningFeed";
import HealthGrid from "./components/HealthGrid";
import AnomalyScoreChart from "./components/AnomalyScoreChart";
import LSTMPredictionChart from "./components/LSTMPredictionChart";
import DependencyGraph from "./components/DependencyGraph";
import DecisionTraceTable from "./components/DecisionTraceTable";


export default function App() {
  const { data, connected } = useNovaSurgeStream();

  return (
    <div className="bg-[#0f172a] text-white min-h-screen w-full overflow-hidden flex flex-col">
      {/* Header */}
      <div className="p-2 text-xl font-bold">
        NovaSurge Dashboard {connected ? "🟢" : "🔴"}
      </div>

      {/* Grid */}
      <div className="flex-1 grid grid-cols-12 grid-rows-6 gap-2 p-2">
        {/* Reasoning Feed */}
        <div className="col-span-6 row-span-2 bg-[#1e293b] rounded p-2 overflow-hidden">
          <h2 className="text-lg font-bold mb-2">Reasoning Feed</h2>
          <ReasoningFeed data={data} />
        </div>

        {/* Health Grid */}
        <div className="col-span-3 row-span-2 bg-[#1e293b] rounded p-2 overflow-hidden">
          <h2 className="text-lg font-bold">System Health</h2>
          <HealthGrid scores={data?.scores} />
        </div>

        {/* LSTM Prediction */}
        <div className="col-span-3 row-span-3 bg-[#1e293b] rounded p-2 overflow-hidden">
          <h2 className="text-lg font-bold">LSTM Prediction</h2>
          <LSTMPredictionChart prediction={data?.lstm_prediction} />
        </div>

        {/* Anomaly Chart */}
        <div className="col-span-4 row-span-3 bg-[#1e293b] rounded p-2 overflow-hidden">
          <h2 className="text-lg font-bold">Anomaly Score</h2>
          <AnomalyScoreChart scores={data?.scores} />
        </div>

        {/* Decision Table */}
        <div className="col-span-5 row-span-3 bg-[#1e293b] rounded p-2 overflow-hidden">
          <h2 className="text-lg font-bold">Decision Trace</h2>
          <DecisionTraceTable trace={data?.decision_trace || []} />
        </div>

        {/* Dependency Graph */}
        <div className="col-span-3 row-span-3 bg-[#1e293b] rounded p-2 overflow-hidden">
          <h2 className="text-lg font-bold">Dependency Graph</h2>
          <div className="bg-[#1e293b] p-4 rounded-xl h-[400px] overflow-hidden">
            <DependencyGraph graph={data?.dependency_graph} />
          </div>
        </div>
      </div>
    </div>
  );
}
