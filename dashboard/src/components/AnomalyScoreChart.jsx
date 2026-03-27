import { useState, useEffect, useRef } from "react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer
} from "recharts";

export default function AnomalyScoreChart({ scores }) {
  const [data, setData] = useState([]);
  const lastScoreRef = useRef(null); // ✅ prevents duplicate updates

  useEffect(() => {
    if (!scores) return;

    const currentScore = scores["order-service"];

    // ✅ avoid unnecessary updates
    if (lastScoreRef.current === currentScore) return;
    lastScoreRef.current = currentScore;

    const newPoint = {
      time: new Date().toLocaleTimeString(),
      score: currentScore
    };

    // eslint-disable-next-line react-hooks/set-state-in-effect
    setData((prev) => {
      const updated = [...prev, newPoint];
      return updated.slice(-20);
    });

  }, [scores]);

  return (
  <div className="h-full flex flex-col overflow-hidden">
    
    {/* <h2 className="text-lg font-bold mb-2">
      Anomaly Score
    </h2> */}

    {/* FIXED HEIGHT CONTAINER */}
    <div className="h-[220px] w-full">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data}>
          <XAxis 
            dataKey="time"
            tick={{ fontSize: 10 }}
            interval="preserveStartEnd"
          />

          <YAxis 
            domain={[-1, 0]} 
            tick={{ fontSize: 10 }}
            width={30}
          />

          <Tooltip />

          <Line
            type="monotone"
            dataKey="score"
            stroke="#ef4444"
            strokeWidth={2}
            dot={false}
            isAnimationActive={true}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  </div>
);
}