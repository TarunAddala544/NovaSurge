import { useState, useEffect, useRef } from "react";
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  ReferenceLine,
  ResponsiveContainer,
} from "recharts";

const ACTUAL_WINDOW  = 20;
const PREDICT_WINDOW = 6;
const DEFAULT_SERVICE = "payment-service";

function formatTime(ts) {
  if (!ts) return "";
  const d = new Date(ts);
  return d.toLocaleTimeString("en-US", { hour12: false });
}

export default function LSTMPredictionChart({ buffer, streamData }) {
  const [chartData, setChartData] = useState([]);
  const [targetService, setTargetService] = useState(DEFAULT_SERVICE);
  const [predWarning, setPredWarning] = useState(false);

  useEffect(() => {
    if (!streamData) return;

    // Pick service: anomalous service or default
    const anomService = streamData?.anomaly?.affected_service;
    const activeSvc = anomService || DEFAULT_SERVICE;
    setTargetService(activeSvc);

    // Actual scores from buffer
    const actualPoints = (buffer || [])
      .slice(-ACTUAL_WINDOW)
      .map((msg) => ({
        time: formatTime(msg.timestamp),
        actual: msg.scores?.[activeSvc] ?? null,
        predicted: null,
        isPredicted: false,
      }));

    // Prediction point(s) from lstm_predictions
    const pred = streamData?.lstm_predictions?.[activeSvc];
    const isPredAnomaly = pred?.predicted_anomaly ?? false;
    setPredWarning(isPredAnomaly);

    if (pred) {
      for (let i = 1; i <= PREDICT_WINDOW; i++) {
        const futureTime = new Date(
          Date.now() + i * 10000
        ).toLocaleTimeString("en-US", { hour12: false });
        // Linearly interpolate toward predicted_score_60s
        const lastActual = actualPoints[actualPoints.length - 1]?.actual ?? 0;
        const slope = (pred.predicted_score_60s - lastActual) / PREDICT_WINDOW;
        actualPoints.push({
          time: futureTime,
          actual: null,
          predicted: lastActual + slope * i,
          isPredicted: true,
        });
      }
    }

    setChartData(actualPoints);
  }, [buffer, streamData]);

  const currentTimestamp =
    chartData.find((p) => !p.isPredicted && p.actual !== null)?.time ?? null;

  // Find boundary between actual and predicted
  const splitIndex = chartData.findIndex((p) => p.isPredicted);
  const splitTime = splitIndex > 0 ? chartData[splitIndex].time : null;

  return (
    <div className="h-full flex flex-col overflow-hidden">
      <div className="text-xs font-semibold text-slate-400 mb-1 shrink-0">
        LSTM Prediction:{" "}
        <span className="text-blue-300">{targetService}</span>
      </div>

      {predWarning && (
        <div className="text-xs font-bold text-red-400 mb-1 shrink-0 animate-pulse">
          ⚠ Degradation predicted in ~60s
        </div>
      )}

      <div className="flex-1 min-h-0">
        <ResponsiveContainer width="100%" height={300} minHeight={200}>
          <AreaChart
            data={chartData}
            margin={{ top: 4, right: 4, left: -20, bottom: 0 }}
          >
            <defs>
              <linearGradient id="actualGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%"  stopColor="#3b82f6" stopOpacity={0.3} />
                <stop offset="95%" stopColor="#3b82f6" stopOpacity={0.05} />
              </linearGradient>
              <linearGradient id="predGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%"  stopColor="#ef4444" stopOpacity={0.1} />
                <stop offset="95%" stopColor="#ef4444" stopOpacity={0.02} />
              </linearGradient>
            </defs>

            <XAxis
              dataKey="time"
              tick={{ fontSize: 8, fill: "#64748b" }}
              interval="preserveStartEnd"
            />
            <YAxis
              domain={[-1.0, 0.5]}
              tick={{ fontSize: 8, fill: "#64748b" }}
              width={30}
            />
            <Tooltip
              contentStyle={{
                backgroundColor: "#1e293b",
                border: "1px solid #334155",
                fontSize: 10,
                borderRadius: 6,
              }}
              labelStyle={{ color: "#94a3b8" }}
            />

            {/* Vertical warning line at transition to predicted */}
            {splitTime && predWarning && (
              <ReferenceLine
                x={splitTime}
                stroke="#ef4444"
                strokeDasharray="4 3"
                label={{
                  value: "NOW",
                  position: "top",
                  style: { fill: "#ef4444", fontSize: 8 },
                }}
              />
            )}

            {/* Actual scores area */}
            <Area
              type="monotone"
              dataKey="actual"
              stroke="#3b82f6"
              strokeWidth={1.5}
              fill="url(#actualGrad)"
              dot={false}
              isAnimationActive={false}
              connectNulls={false}
            />

            {/* Predicted scores area */}
            <Area
              type="monotone"
              dataKey="predicted"
              stroke="#ef4444"
              strokeWidth={1.5}
              strokeDasharray="5 3"
              fill="url(#predGrad)"
              dot={false}
              isAnimationActive={false}
              connectNulls={false}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}