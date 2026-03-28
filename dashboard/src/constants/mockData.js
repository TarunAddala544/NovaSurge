// Exact MOCK_STREAM from the prompt spec.
// Cycles through phases every 8 seconds when WebSocket is disconnected.

const PHASES = ["DETECTING", "RECOVERING", "IDLE"];
let _phaseIndex = 0;
let _lastPhaseSwitch = Date.now();

function getCurrentPhase() {
  const now = Date.now();
  if (now - _lastPhaseSwitch > 8000) {
    _phaseIndex = (_phaseIndex + 1) % PHASES.length;
    _lastPhaseSwitch = now;
  }
  return PHASES[_phaseIndex];
}

export function MOCK_STREAM() {
  const phase = getCurrentPhase();
  const now = new Date().toISOString();

  // Vary order-service score by phase
  const orderScore =
    phase === "DETECTING"
      ? -0.71
      : phase === "RECOVERING"
      ? -0.4 - Math.random() * 0.1
      : -0.04 - Math.random() * 0.02;

  const anomalyDetected = phase === "DETECTING" || phase === "RECOVERING";

  return {
    timestamp: now,

    scores: {
      "api-gateway":           -0.03,
      "product-service":       -0.04,
      "order-service":         orderScore,
      "payment-service":       -0.02,
      "notification-service":  -0.01,
    },

    anomaly: anomalyDetected
      ? {
          anomaly_detected: true,
          affected_service: "order-service",
          anomaly_type: "high_latency",
          severity_score: 0.74,
          iforest_score: -0.71,
          lstm_reconstruction_error: 0.089,
          feature_deltas: { p99_latency: 4.2, error_rate: 0.3 },
          detected_at: now,
        }
      : null,

    reasoning:
      phase === "DETECTING"
        ? "Anomaly confirmed on order-service. p99 latency spiked 340% over 3 consecutive windows. Isolation Forest score: -0.71. Root cause localized to order-service. Resource exhaustion pattern. Executing HPA scale-out."
        : phase === "RECOVERING"
        ? "order-service scaled from 1 to 3 replicas. All replicas healthy. p99 latency normalized from 1240 to 210. Load distributed. Recovery confirmed in 27 seconds."
        : null,

    metrics_snapshot: {
      "order-service": {
        http_request_rate: 12.3,
        error_rate: 0.08,
        p99_latency: phase === "DETECTING" ? 1240 : 210,
        cpu_usage: phase === "DETECTING" ? 0.89 : 0.42,
        memory_usage: 445,
        active_connections: 8,
      },
    },

    lstm_predictions: {
      "order-service": {
        predicted_score_60s: -0.85,
        predicted_anomaly: anomalyDetected,
        confidence: 0.78,
      },
    },

    round_status: {
      current_round: 2,
      phase: phase === "DETECTING" ? "DETECTING" : phase === "RECOVERING" ? "RECOVERING" : "IDLE",
      elapsed_seconds: Math.floor((Date.now() - _lastPhaseSwitch) / 1000),
      failure_type: anomalyDetected ? "high_latency" : null,
    },

    dependency_graph: {
      nodes: [
        { id: "api-gateway",          health: "healthy", score: -0.03, request_rate: 48.2 },
        { id: "order-service",        health: anomalyDetected ? "anomaly" : "healthy", score: orderScore, request_rate: 12.3 },
        { id: "payment-service",      health: "healthy", score: -0.02, request_rate: 9.1  },
        { id: "product-service",      health: "healthy", score: -0.04, request_rate: 33.5 },
        { id: "notification-service", health: "healthy", score: -0.01, request_rate: 6.2  },
      ],
      edges: [
        { source: "api-gateway",   target: "order-service",   weight: 0.9 },
        { source: "api-gateway",   target: "product-service", weight: 0.7 },
        { source: "api-gateway",   target: "payment-service", weight: 0.5 },
        { source: "order-service", target: "payment-service", weight: 0.8 },
        { source: "order-service", target: "product-service", weight: 0.6 },
      ],
    },
  };
}

// Static mock rounds data for DecisionTraceTable fallback
export const MOCK_ROUNDS = [
  {
    round: 1,
    failure_type: "pod_crash",
    service: "payment-service",
    if_score: -0.82,
    decision: "pod-restart",
    remediator: "KubernetesRemediator",
    recovery_s: 18,
    rca_origin: "OOMKilled container",
    status: "COMPLETE",
  },
  {
    round: 2,
    failure_type: "high_latency",
    service: "order-service",
    if_score: -0.71,
    decision: "hpa-scaleout",
    remediator: "HPARemediator",
    recovery_s: 27,
    rca_origin: "CPU limit exhaustion",
    status: "RECOVERING",
  },
];