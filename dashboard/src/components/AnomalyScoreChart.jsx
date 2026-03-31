import { useState, useEffect, useRef } from "react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ReferenceLine,
  Legend,
  ResponsiveContainer,
  ReferenceDot,
} from "recharts";

const SERVICE_COLORS = {
  "api-gateway":          "#3b82f6",
  "product-service":      "#8b5cf6",
  "order-service":        "#f59e0b",
  "payment-service":      "#10b981",
  "notification-service": "#6b7280",
};

const SERVICES = Object.keys(SERVICE_COLORS);
const ANOMALY_THRESHOLD = -0.15;

function formatTime(ts) {
  if (!ts) return "";
  const d = new Date(ts);
  return d.toLocaleTimeString("en-US", { hour12: false, hour: "2-digit", minute: "2-digit" });
}

export default function AnomalyScoreChart({ buffer }) {
  // Build chart data from rolling buffer
  const chartData = (buffer || []).map((msg) => ({
    time: formatTime(msg.timestamp),
    ...Object.fromEntries(
      SERVICES.map((svc) => [svc, msg.scores?.[svc] ?? null])
    ),
  }));

  // Find any crossing points (for pulsing dots)
  const crossings = [];
  chartData.forEach((point, i) => {
    SERVICES.forEach((svc) => {
      const val = point[svc];
      if (val !== null && val < ANOMALY_THRESHOLD) {
        const prev = i > 0 ? chartData[i - 1][svc] : null;
        if (prev === null || prev >= ANOMALY_THRESHOLD) {
          crossings.push({ svc, index: i, value: val, time: point.time });
        }
      }
    });
  });

  // Which services are currently below threshold
  const lastPoint = chartData[chartData.length - 1];
  const alertedServices = lastPoint
    ? SERVICES.filter((s) => (lastPoint[s] ?? 0) < ANOMALY_THRESHOLD)
    : [];

  const CustomDot = ({ cx, cy, dataKey }) => {
    const isAlerted = alertedServices.includes(dataKey);
    if (!isAlerted || cx === undefined || cy === undefined) return null;
    return (
      <circle
        cx={cx}
        cy={cy}
        r={5}
        fill={SERVICE_COLORS[dataKey]}
        stroke="white"
        strokeWidth={1}
        className="animate-ping"
        style={{ transformOrigin: `${cx}px ${cy}px` }}
      />
    );
  };

  return (
    <div className="h-full flex flex-col overflow-hidden">
      <ResponsiveContainer width="100%" height={300} minHeight={200}>
        <LineChart
          data={chartData}
          margin={{ top: 8, right: 8, left: -10, bottom: 0 }}
        >
          <XAxis
            dataKey="time"
            tick={{ fontSize: 9, fill: "#94a3b8" }}
            interval="preserveStartEnd"
          />
          <YAxis
            domain={[-1.0, 0.5]}
            tick={{ fontSize: 9, fill: "#94a3b8" }}
            label={{
              value: "Anomaly Score",
              angle: -90,
              position: "insideLeft",
              style: { fill: "#64748b", fontSize: 9 },
              offset: 10,
            }}
            width={45}
          />
          <Tooltip
            contentStyle={{
              backgroundColor: "#1e293b",
              border: "1px solid #334155",
              borderRadius: 6,
              fontSize: 10,
            }}
            labelStyle={{ color: "#94a3b8" }}
          />
          <Legend
            wrapperStyle={{ fontSize: 9, paddingTop: 4 }}
            formatter={(value) => (
              <span
                style={{
                  color: alertedServices.includes(value) ? "#ef4444" : "#94a3b8",
                  fontWeight: alertedServices.includes(value) ? "bold" : "normal",
                }}
              >
                {value}
              </span>
            )}
          />

          {/* Threshold line */}
          <ReferenceLine
            y={ANOMALY_THRESHOLD}
            stroke="#ef4444"
            strokeDasharray="4 3"
            label={{
              value: "Anomaly Threshold",
              position: "insideTopRight",
              style: { fill: "#ef4444", fontSize: 9 },
            }}
          />

          {SERVICES.map((svc) => (
            <Line
              key={svc}
              type="monotone"
              dataKey={svc}
              stroke={SERVICE_COLORS[svc]}
              strokeWidth={alertedServices.includes(svc) ? 2.5 : 1.5}
              dot={false}
              isAnimationActive={false}
              connectNulls
            />
          ))}

          {/* Pulsing dots at first crossing point per service */}
          {crossings.map((c, i) => (
            <ReferenceDot
              key={`cross-${i}`}
              x={c.time}
              y={c.value}
              r={5}
              fill={SERVICE_COLORS[c.svc]}
              stroke="white"
              strokeWidth={1}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}