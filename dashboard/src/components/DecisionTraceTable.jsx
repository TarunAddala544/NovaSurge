import React from "react";

const statusColor = {
  anomaly: "bg-red-500",
  analysis: "bg-yellow-500",
  warning: "bg-orange-500",
  action: "bg-blue-500",
  executed: "bg-green-500"
};

export default function DecisionTrace({ trace=[] }) {
  return (
    <div className="bg-[#1e293b] p-4 rounded-xl h-full flex flex-col gap-4">
      <h2 className="text-white font-semibold">AI Decision Flow</h2>

      <div className="flex flex-col gap-4 overflow-y-auto">
        {trace.map((item, index) => (
          <div key={index} className="flex items-start gap-3">
            
            {/* Step Indicator */}
            <div className={`w-3 h-3 mt-2 rounded-full ${statusColor[item.status]}`} />

            {/* Content */}
            <div>
              <p className="text-white font-medium">{item.step}</p>
              <p className="text-gray-400 text-sm">{item.message}</p>
            </div>

          </div>
        ))}
      </div>
    </div>
  );
}