export const MOCK_STREAM = () => {
    const score = -1 - Math.random() * 0.8; 
    const now = new Date().toISOString();

    const latency = Math.floor(1000 + Math.random() * 500);
    const delta = (Math.random() * 4 + 2).toFixed(1);

    // 🔥 DYNAMIC DECISION TRACE
    const decision_trace = [
        {
            step: "Detection",
            status: "anomaly",
            message: `Latency spike detected in order-service (${latency}ms)`
        },
        {
            step: "Root Cause",
            status: "analysis",
            message: "High retry rate observed from api-gateway → order-service"
        },
        {
            step: "Prediction",
            status: "warning",
            message: `Failure likely within 60s (confidence ${(0.7 + Math.random() * 0.2).toFixed(2)})`
        },
        {
            step: "Decision",
            status: "action",
            message: "Triggering horizontal pod autoscaling (HPA)"
        },
        {
            step: "Action",
            status: "executed",
            message: "Scaled order-service from 1 → 3 pods"
        }
    ];

    return {
        timestamp: now,

        scores: {
            "api-gateway": -0.03,
            "product-service": -0.04,
            "order-service": -0.6 - Math.random() * 0.2,
            "payment-service": -0.02,
            "notification-service": -0.01
        },

        anomaly: {
            anomaly_detected: true,
            affected_service: "order-service",
            anomaly_type: "high_latency",
            severity_score: Math.random(),
            iforest_score: -0.7,
            lstm_reconstruction_error: 0.08,
            feature_deltas: {
                p99_latency: delta,
                error_rate: Math.random() * 0.5
            },
            detected_at: now
        },

        // 🔥 DYNAMIC REASONING TEXT (UPGRADED)
        reasoning: `Latency spike detected in order-service (${latency}ms, ${delta}x increase). Isolation Forest flagged anomaly (score -0.7). LSTM predicts cascading failure risk. Initiating HPA scale-out.`,

        metrics_snapshot: {
            "order-service": {
                http_request_rate: 10 + Math.random() * 5,
                error_rate: Math.random() * 0.1,
                p99_latency: latency,
                cpu_usage: Math.random(),
                memory_usage: 400 + Math.random() * 100,
                active_connections: Math.floor(Math.random() * 10)
            }
        },

        lstm_predictions: {
            "order-service": {
                predicted_score_60s: -0.85,
                predicted_anomaly: true,
                confidence: 0.7 + Math.random() * 0.2
            }
        },

        round_status: {
            current_round: Math.floor(Math.random() * 5) + 1,
            phase: ["DETECTING", "ANALYZING", "RECOVERING"][
                Math.floor(Math.random() * 3)
            ],
            elapsed_seconds: Math.floor(Math.random() * 60),
            failure_type: "high_latency"
        },

        dependency_graph: {
            nodes: [
                { id: "api-gateway", health: "healthy", score: -0.03 },
                { id: "order-service", health: "anomaly", score: -0.7 },
                { id: "payment-service", health: "healthy", score: -0.02 },
                { id: "product-service", health: "healthy", score: -0.04 },
                { id: "notification-service", health: "healthy", score: -0.01 }
            ],
            edges: [
                { source: "api-gateway", target: "order-service", weight: 0.9 },
                { source: "order-service", target: "payment-service", weight: 0.8 }
            ]
        },

        // 🔥 NEW FIELD (IMPORTANT)
        decision_trace: decision_trace,

        // existing logic (kept as-is)
        lstm_prediction: {
            "order-service": {
                predicted_score_60s: score,
                predicted_anomaly: score < -0.6,
                confidence: 0.5 + Math.random() * 0.5
            }
        }
    };
};