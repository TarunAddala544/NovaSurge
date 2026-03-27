export default function HealthGrid({ scores }) {
  if (!scores) return null;

  const getStatus = (score) => {
    if (score < -0.5) return "anomaly";
    if (score < -0.2) return "warning";
    return "healthy";
  };

  const getColor = (status) => {
    if (status === "anomaly") return "bg-red-500";
    if (status === "warning") return "bg-yellow-500";
    return "bg-green-500";
  };

  return (
    <div className="h-full flex flex-col">
      {/* <h2 className="text-lg font-bold mb-2">System Health</h2> */}

      <div className="grid grid-cols-2 gap-2">
        {Object.entries(scores).map(([service, score]) => {
          const status = getStatus(score);

          return (
            <div
              key={service}
              className={`p-3 rounded bg-[#0f172a] border border-slate-700 ${
                status === "anomaly" ? "animate-pulse" : ""
              }`}
            >
              <div className="flex justify-between items-center mb-1">
                <span className="text-sm font-semibold">{service}</span>

                <span
                  className={`w-3 h-3 rounded-full ${getColor(status)}`}
                ></span>
              </div>

              <div className="text-xs text-gray-400">
                Score: {score.toFixed(3)}
              </div>

              <div className="text-xs mt-1 capitalize text-gray-300">
                Status: {status}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}