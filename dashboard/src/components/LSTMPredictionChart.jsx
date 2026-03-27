export default function LSTMPredictionChart({ prediction }) {
  // ✅ DEBUG (remove later if you want)
  console.log("LSTM Prediction:", prediction);

  // ❌ no data
  if (!prediction || Object.keys(prediction).length === 0) {
    return (
      <div className="h-full flex items-center justify-center text-gray-400 text-sm">
        Waiting for prediction data...
      </div>
    );
  }

  const service = Object.keys(prediction)[0];
  const data = prediction[service];

  // ❌ invalid structure
  if (!data) {
    return (
      <div className="h-full flex items-center justify-center text-gray-400 text-sm">
        Invalid prediction format
      </div>
    );
  }

  const score = data.predicted_score_60s ?? 0;
  const isAnomaly = data.predicted_anomaly ?? false;
  const confidence = data.confidence ?? 0;

  const getColor = () => {
    return isAnomaly ? "bg-red-500" : "bg-green-500";
  };

  const getLabel = () => {
    return isAnomaly ? "High Risk Incoming" : "System Stable";
  };

  return (
    <div className="h-full flex flex-col overflow-hidden">
      
      {/* <h2 className="text-lg font-bold mb-2">
        LSTM Prediction (60s Ahead)
      </h2> */}

      <div className="flex-1 flex flex-col justify-center items-center gap-4">

        {/* STATUS */}
        <div className={`px-4 py-2 rounded text-sm ${getColor()}`}>
          {getLabel()}
        </div>

        {/* SCORE BAR */}
        <div className="w-full">
          <div className="text-xs mb-1 text-gray-400">
            Predicted Score
          </div>

          <div className="w-full h-3 bg-slate-700 rounded">
            <div
              className={`h-3 rounded ${getColor()}`}
              style={{
                width: `${Math.min(Math.abs(score) * 100, 100)}%`
              }}
            />
          </div>

          <div className="text-xs mt-1 text-gray-300">
            {score.toFixed(3)}
          </div>
        </div>

        {/* CONFIDENCE */}
        <div className="w-full">
          <div className="text-xs mb-1 text-gray-400">
            Confidence
          </div>

          <div className="w-full h-3 bg-slate-700 rounded">
            <div
              className="h-3 rounded bg-blue-500"
              style={{
                width: `${Math.min(confidence * 100, 100)}%`
              }}
            />
          </div>

          <div className="text-xs mt-1 text-gray-300">
            {(confidence * 100).toFixed(1)}%
          </div>
        </div>

      </div>
    </div>
  );
}