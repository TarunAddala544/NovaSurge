"""
novasurge/decision_engine.py

Maps anomaly types to remediations, applies 4 guardrails, confidence
scoring via SQLite history, and returns a full decision dict.
"""

from __future__ import annotations

import json

from novasurge.k8s_client import get_clients, NAMESPACE
from novasurge.state_manager import (
    is_active,
    mark_active,
    get_active_count,
    get_all_active_services,
)
from novasurge.state_db import (
    get_historical_success_rate,
    get_recent_failed_remediations,
    record_guardrail,
)

# ── Decision map ──────────────────────────────────────────────────────────────
DECISION_MAP: dict[str, list[str]] = {
    "pod_crash":          ["pod_restart",     "hpa_scaleout"],
    "oom_kill":           ["hpa_scaleout",    "pod_restart"],
    "cpu_throttle":       ["hpa_scaleout",    "cache_flush"],
    "network_partition":  ["traffic_reroute", "pod_restart"],
    "replica_exhaustion": ["hpa_scaleout",    "traffic_reroute"],
    "cache_miss_spike":   ["cache_flush",     "hpa_scaleout"],
    "high_latency":       ["cache_flush",     "hpa_scaleout"],
}

# ── Business-impact weights ───────────────────────────────────────────────────
BUSINESS_IMPACT: dict[str, int] = {
    "payment-service":       10,
    "api-gateway":            9,
    "order-service":          8,
    "product-service":        6,
    "notification-service":   2,
}

CASCADE_THRESHOLD = 2
CONFIDENCE_THRESHOLD = 0.4


# ── Confidence scoring ────────────────────────────────────────────────────────
def compute_confidence(
    service: str,
    remediator: str,
    rca_confidence: float,
    blast_radius_score: int = 0,
) -> float:
    """
    confidence = historical_success_rate
                 x rca_confidence
                 x (1 - normalized_blast_risk x 0.3)

    Falls back to 0.7 prior when no SQLite history exists yet.
    Returns float 0.0-1.0.
    """
    historical_rate = get_historical_success_rate(service, remediator)
    blast_risk = min(blast_radius_score / 5.0, 1.0)
    confidence = historical_rate * rca_confidence * (1 - blast_risk * 0.3)
    confidence = round(max(0.0, min(confidence, 1.0)), 3)
    print(
        f"[decision_engine] Confidence for '{remediator}' on '{service}': {confidence:.3f} "
        f"(historical={historical_rate:.2f}, rca_conf={rca_confidence:.2f}, "
        f"blast_risk={blast_risk:.2f})"
    )
    return confidence


# ── Replica helper ────────────────────────────────────────────────────────────
def _get_current_replicas(service: str) -> int:
    try:
        _, apps_v1, _, _ = get_clients()
        dep = apps_v1.read_namespaced_deployment(name=service, namespace=NAMESPACE)
        return dep.status.ready_replicas or 1
    except Exception:
        return 2  # safe default


# ── Main decide function ──────────────────────────────────────────────────────
def decide(
    anomaly_payload: dict,
    rca_result: dict,
    round_num: int = 0,
    blast_radius_score: int = 0,
    metrics_snapshot: dict | None = None,
) -> dict:
    """
    Build a remediation decision with full guardrail processing
    and confidence scoring.

    Returns
    -------
    {
        "service":               str,
        "anomaly_type":          str,
        "priority":              float,
        "primary_remediation":   str,
        "fallback_remediation":  str,
        "confidence":            float,
        "guardrails_triggered":  list[str],
        "reasoning_text":        str,
    }
    """
    service = rca_result.get(
        "true_origin", anomaly_payload.get("affected_service", "unknown")
    )
    anomaly_type = anomaly_payload.get("anomaly_type", "high_latency")
    severity = float(anomaly_payload.get("severity_score", 0.5))
    rca_confidence = float(rca_result.get("confidence", 0.7))

    impact_weight = BUSINESS_IMPACT.get(service, 5)
    priority = round(impact_weight * severity, 4)

    remediations = DECISION_MAP.get(anomaly_type, ["hpa_scaleout", "pod_restart"])
    primary = remediations[0]
    fallback = remediations[1] if len(remediations) > 1 else remediations[0]

    guardrails_triggered: list[str] = []
    reasoning_lines: list[str] = [
        f"Service '{service}' | anomaly='{anomaly_type}' | severity={severity:.2f} | "
        f"impact_weight={impact_weight} | priority={priority:.4f}",
        f"Initial remediation plan: primary='{primary}', fallback='{fallback}'",
    ]

    # ── GUARDRAIL 1: No duplicate active remediation ──────────────────────────
    if is_active(service):
        msg = (
            f"Guardrail 1 TRIGGERED: duplicate remediation blocked — "
            f"'{service}' already has an active remediation in progress."
        )
        print(f"[decision_engine] {msg}")
        guardrails_triggered.append("G1_DUPLICATE_BLOCKED")
        reasoning_lines.append(msg)
        record_guardrail(round_num, 1, service, primary, "BLOCKED", msg)
        return _build_result(
            service, anomaly_type, priority,
            primary="BLOCKED", fallback=fallback,
            guardrails=guardrails_triggered,
            reasoning=reasoning_lines,
            confidence=0.0,
        )

    # ── GUARDRAIL 2: Minimum replica safety ───────────────────────────────────
    if primary == "pod_restart":
        current_replicas = _get_current_replicas(service)
        if current_replicas <= 1:
            msg = (
                f"Guardrail 2 TRIGGERED: replica safety — '{service}' has only "
                f"{current_replicas} replica(s). Switching to hpa_scaleout first, "
                f"then pod_restart as fallback."
            )
            print(f"[decision_engine] {msg}")
            guardrails_triggered.append("G2_REPLICA_SAFETY")
            reasoning_lines.append(msg)
            record_guardrail(round_num, 2, service, "pod_restart", "hpa_scaleout", msg)
            primary = "hpa_scaleout"
            fallback = "pod_restart"

    # ── GUARDRAIL 3: Recent failure memory (SQLite-backed) ──────────────────
    if get_recent_failed_remediations(service, primary, within_seconds=120):
        msg = (
            f"Guardrail 3 TRIGGERED: recent failure memory — '{primary}' on '{service}' "
            f"failed within the last 120s. Switching to fallback '{fallback}'."
        )
        print(f"[decision_engine] {msg}")
        guardrails_triggered.append("G3_RECENT_FAILURE_FALLBACK")
        reasoning_lines.append(msg)
        record_guardrail(round_num, 3, service, primary, fallback, msg)
        primary, fallback = fallback, primary

    # ── GUARDRAIL 4: Cascade protection ───────────────────────────────────────
    active_count = get_active_count()
    if active_count >= CASCADE_THRESHOLD:
        all_active = get_all_active_services()
        candidates = {service: priority}
        for active_svc in all_active:
            active_impact = BUSINESS_IMPACT.get(active_svc, 5)
            candidates[active_svc] = active_impact * severity

        highest_priority_svc = max(candidates, key=lambda s: candidates[s])
        if highest_priority_svc != service:
            msg = (
                f"Guardrail 4 TRIGGERED: cascade protection — {active_count} services "
                f"currently remediating ({', '.join(all_active)}). "
                f"'{service}' deferred 30s; only '{highest_priority_svc}' will proceed now."
            )
            print(f"[decision_engine] {msg}")
            guardrails_triggered.append("G4_CASCADE_DEFER_30S")
            reasoning_lines.append(msg)
            record_guardrail(round_num, 4, service, primary, "DEFERRED_30S", msg)
            return _build_result(
                service, anomaly_type, priority,
                primary="DEFERRED_30S", fallback=fallback,
                guardrails=guardrails_triggered,
                reasoning=reasoning_lines,
                confidence=0.0,
            )
        else:
            msg = (
                f"Guardrail 4 CHECK: cascade protection evaluated — {active_count} services "
                f"active, but '{service}' is the highest-priority; proceeding."
            )
            print(f"[decision_engine] {msg}")
            guardrails_triggered.append("G4_CASCADE_HIGHEST_PRIORITY_PROCEED")
            reasoning_lines.append(msg)

    # ── Confidence scoring ────────────────────────────────────────────────────
    confidence = compute_confidence(service, primary, rca_confidence, blast_radius_score)

    if confidence < CONFIDENCE_THRESHOLD:
        msg = (
            f"Confidence {confidence:.3f} below threshold {CONFIDENCE_THRESHOLD} "
            f"— escalating from '{primary}' to fallback '{fallback}'."
        )
        print(f"[decision_engine] {msg}")
        reasoning_lines.append(msg)
        primary, fallback = fallback, primary
        confidence = compute_confidence(
            service, primary, rca_confidence, blast_radius_score
        )

    # ── Final decision ────────────────────────────────────────────────────────
    reasoning_lines.append(
        f"Final decision: apply '{primary}' on '{service}' "
        f"(fallback='{fallback}', confidence={confidence:.3f}, "
        f"guardrails={guardrails_triggered or 'none'})."
    )

    return _build_result(
        service, anomaly_type, priority,
        primary=primary, fallback=fallback,
        guardrails=guardrails_triggered,
        reasoning=reasoning_lines,
        confidence=confidence,
    )


def _build_result(
    service: str,
    anomaly_type: str,
    priority: float,
    primary: str,
    fallback: str,
    guardrails: list[str],
    reasoning: list[str],
    confidence: float = 0.0,
) -> dict:
    return {
        "service": service,
        "anomaly_type": anomaly_type,
        "priority": priority,
        "primary_remediation": primary,
        "fallback_remediation": fallback,
        "confidence": confidence,
        "guardrails_triggered": guardrails,
        "reasoning_text": " | ".join(reasoning),
    }


# ── Standalone test ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    import os
    os.environ.setdefault("NOVASURGE_MOCK_K8S", "true")

    sample_anomaly = {
        "anomaly_detected": True,
        "affected_service": "order-service",
        "anomaly_type": "high_latency",
        "severity_score": 0.74,
    }
    sample_rca = {
        "true_origin": "order-service",
        "confidence": 0.87,
        "call_path": ["api-gateway", "order-service"],
        "reasoning": "order-service deviates independently",
    }

    result = decide(sample_anomaly, sample_rca, round_num=1, blast_radius_score=1)
    print(json.dumps(result, indent=2))
