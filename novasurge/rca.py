"""
novasurge/rca.py

Root-cause analysis using a hardcoded service dependency graph.
analyze(anomaly_payload, metrics_snapshot) → dict
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

# ── Dependency graph: key calls all services in value list ───────────────────
DEPENDENCY_GRAPH: dict[str, list[str]] = {
    "api-gateway":          ["product-service", "order-service", "payment-service"],
    "order-service":        ["product-service", "payment-service"],
    "payment-service":      [],
    "product-service":      [],
    "notification-service": [],
}

# Pre-compute reverse map: who calls X?
def _build_caller_map() -> dict[str, list[str]]:
    callers: dict[str, list[str]] = {s: [] for s in DEPENDENCY_GRAPH}
    for caller, callees in DEPENDENCY_GRAPH.items():
        for callee in callees:
            callers[callee].append(caller)
    return callers

CALLER_MAP = _build_caller_map()

LATENCY_DEVIATION_THRESHOLD = 1.5   # ratio vs baseline
ERROR_RATE_DEVIATION_THRESHOLD = 0.05  # absolute delta


def _is_deviated(svc_metrics: dict) -> bool:
    """True if this service's metrics look anomalous."""
    latency_ratio = svc_metrics.get("latency_ratio", 1.0)
    error_delta = svc_metrics.get("error_rate_delta", 0.0)
    return (
        latency_ratio >= LATENCY_DEVIATION_THRESHOLD
        or error_delta >= ERROR_RATE_DEVIATION_THRESHOLD
    )


def analyze(anomaly_payload: dict, metrics_snapshot: dict) -> dict:
    """
    Parameters
    ----------
    anomaly_payload  : dict from anomaly endpoint (affected_service, anomaly_type, …)
    metrics_snapshot : dict keyed by service name, each value has:
                       {latency_ratio, error_rate_delta, timestamp_offset_seconds}

    Returns
    -------
    {
        "true_origin":  str,
        "confidence":   float,
        "call_path":    list[str],
        "reasoning":    str,
    }
    """
    affected = anomaly_payload.get("affected_service", "")
    anomaly_type = anomaly_payload.get("anomaly_type", "unknown")
    severity = anomaly_payload.get("severity_score", 0.5)

    callers = CALLER_MAP.get(affected, [])

    # Build per-service deviation flags
    deviations: dict[str, bool] = {}
    for svc, m in metrics_snapshot.items():
        deviations[svc] = _is_deviated(m)

    # ── Case 1: affected_service deviates BEFORE (or alone vs) its callers ──
    affected_deviated = deviations.get(affected, True)
    callers_deviated = [c for c in callers if deviations.get(c, False)]

    if affected_deviated and not callers_deviated:
        true_origin = affected
        confidence = min(0.55 + severity * 0.4, 0.95)
        call_path = _trace_upstream(true_origin)
        reasoning = (
            f"'{affected}' shows {anomaly_type} deviation independently of its callers "
            f"({', '.join(callers) or 'none'}). "
            f"No upstream caller metrics are anomalous, indicating the fault originated "
            f"in '{affected}' itself. Severity score: {severity:.2f}."
        )
        return {
            "true_origin": true_origin,
            "confidence": round(confidence, 3),
            "call_path": call_path,
            "reasoning": reasoning,
        }

    # ── Case 2: walk upstream — find the earliest deviating service ──────────
    if callers_deviated:
        # Walk up from affected service through deviating callers
        upstream_origin = _walk_upstream(affected, deviations, metrics_snapshot)
        if upstream_origin and upstream_origin != affected:
            confidence = min(0.45 + severity * 0.35, 0.88)
            call_path = _build_call_path(upstream_origin, affected)
            reasoning = (
                f"Cascading deviation detected: callers {callers_deviated} also show "
                f"anomalous metrics. Upstream walk identified '{upstream_origin}' as the "
                f"earliest deviating service. The fault likely propagated downstream to "
                f"'{affected}'. Confidence adjusted for cascade uncertainty."
            )
            return {
                "true_origin": upstream_origin,
                "confidence": round(confidence, 3),
                "call_path": call_path,
                "reasoning": reasoning,
            }

    # ── Case 3: fallback — trust the anomaly detector's affected_service ─────
    confidence = max(0.3, min(0.5 + severity * 0.2, 0.7))
    call_path = _trace_upstream(affected)
    reasoning = (
        f"Insufficient signal to determine upstream origin. Defaulting to reported "
        f"affected service '{affected}' ({anomaly_type}, severity {severity:.2f}). "
        f"Confidence is reduced due to ambiguous metrics."
    )
    return {
        "true_origin": affected,
        "confidence": round(confidence, 3),
        "call_path": call_path,
        "reasoning": reasoning,
    }


def _walk_upstream(
    start: str,
    deviations: dict[str, bool],
    metrics_snapshot: dict,
    visited: set[str] | None = None,
) -> str:
    """Recursively walk to the highest-deviation upstream service."""
    if visited is None:
        visited = set()
    visited.add(start)

    callers = CALLER_MAP.get(start, [])
    deviating_callers = [c for c in callers if deviations.get(c, False) and c not in visited]

    if not deviating_callers:
        return start

    # Pick caller with highest deviation magnitude
    def deviation_magnitude(svc: str) -> float:
        m = metrics_snapshot.get(svc, {})
        return m.get("latency_ratio", 1.0) + m.get("error_rate_delta", 0.0) * 10

    most_deviated_caller = max(deviating_callers, key=deviation_magnitude)
    return _walk_upstream(most_deviated_caller, deviations, metrics_snapshot, visited)


def _trace_upstream(service: str) -> list[str]:
    """Return the call path from a top-level caller down to this service."""
    path = _build_call_path("api-gateway", service)
    if path:
        return path
    return [service]


def _build_call_path(origin: str, target: str) -> list[str]:
    """BFS to find the shortest path from origin to target in the call graph."""
    if origin == target:
        return [origin]
    from collections import deque
    queue: deque[list[str]] = deque([[origin]])
    visited = {origin}
    while queue:
        path = queue.popleft()
        current = path[-1]
        for neighbor in DEPENDENCY_GRAPH.get(current, []):
            if neighbor == target:
                return path + [neighbor]
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append(path + [neighbor])
    return [origin, target]  # fallback direct path


# ── Standalone test ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    sample_anomaly = {
        "anomaly_detected": True,
        "affected_service": "order-service",
        "anomaly_type": "high_latency",
        "severity_score": 0.74,
        "feature_deltas": {"p99_latency": 4.2, "error_rate": 0.1},
    }
    sample_metrics = {
        "order-service":   {"latency_ratio": 3.8, "error_rate_delta": 0.12, "timestamp_offset_seconds": 0},
        "api-gateway":     {"latency_ratio": 1.1, "error_rate_delta": 0.01, "timestamp_offset_seconds": 5},
        "product-service": {"latency_ratio": 1.0, "error_rate_delta": 0.00, "timestamp_offset_seconds": 0},
        "payment-service": {"latency_ratio": 1.2, "error_rate_delta": 0.02, "timestamp_offset_seconds": 0},
    }
    result = analyze(sample_anomaly, sample_metrics)
    print(json.dumps(result, indent=2))
