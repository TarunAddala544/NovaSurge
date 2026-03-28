const SERVICES = [
  "api-gateway",
  "product-service",
  "order-service",
  "payment-service",
  "notification-service",
];

function getStatus(score) {
  if (score < -0.15) return "ANOMALY";
  if (score <= -0.1) return "DEGRADED";
  return "HEALTHY";
}

function getScoreColor(score) {
  if (score < -0.15) return "text-red-400";
  if (score <= -0.1)  return "text-amber-400";
  return "text-emerald-400";
}

function getStatusPill(status) {
  switch (status) {
    case "ANOMALY":  return "bg-red-600 text-white";
    case "DEGRADED": return "bg-amber-500 text-black";
    default:         return "bg-emerald-700 text-white";
  }
}

function getCardBg(status) {
  if (status === "ANOMALY") return "bg-slate-900 border border-red-600 animate-pulse";
  if (status === "DEGRADED") return "bg-slate-900 border border-amber-500";
  return "bg-slate-900 border border-slate-700";
}

export default function HealthGrid({ streamData }) {
  const scores = streamData?.scores ?? {};

  return (
    <div className="h-full grid grid-cols-2 gap-2 content-start">
      {SERVICES.map((svc, idx) => {
        const score = scores[svc] ?? 0;
        const status = getStatus(score);
        // notification-service spans full width (last item, index 4)
        const spanClass = idx === 4 ? "col-span-2" : "";

        return (
          <div
            key={svc}
            className={`p-3 rounded-lg ${getCardBg(status)} ${spanClass}`}
          >
            <div className="flex items-center justify-between mb-1">
              <span className="text-xs font-bold text-slate-200 truncate pr-1">
                {svc}
              </span>
              <span
                className={`px-1.5 py-0.5 text-[10px] font-semibold rounded ${getStatusPill(status)}`}
              >
                {status}
              </span>
            </div>

            <div className={`text-2xl font-mono font-bold ${getScoreColor(score)}`}>
              {score.toFixed(2)}
            </div>
          </div>
        );
      })}
    </div>
  );
}