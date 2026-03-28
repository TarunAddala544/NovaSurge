"""
blast_radius.py — Pre-injection blast radius calculator for NovaSurge.
Runs before every chaos injection in orchestrator.py.
Returns a GO/NO-GO decision with full impact estimate.
Person 4's dashboard can display the preflight card from round JSON.
"""

import json
import os
from datetime import datetime

# Service dependency graph (same as rca.py — source of truth)
DEPENDENCY_GRAPH = {
    "api-gateway":          ["product-service", "order-service", "payment-service"],
    "order-service":        ["product-service", "payment-service"],
    "payment-service":      [],
    "product-service":      [],
    "notification-service": [],
}

# Business impact weights (same as decision_engine.py)
BUSINESS_IMPACT = {
    "payment-service":      10,
    "api-gateway":          9,
    "order-service":        8,
    "product-service":      6,
    "notification-service": 2,
}

# Estimated user traffic percentage each service touches
USER_TRAFFIC_PCT = {
    "api-gateway":          100,
    "order-service":        60,
    "payment-service":      55,
    "product-service":      75,
    "notification-service": 20,
}

# SLA targets per failure type (seconds to recover)
SLA_TARGETS = {
    "pod_deletion":       30,
    "cpu_throttle":       45,
    "network_partition":  60,
    "latency_injection":  40,
    "replica_reduction":  50,
}


def _get_dependents(service):
    """Find all services that call the given service."""
    return [s for s, deps in DEPENDENCY_GRAPH.items() if service in deps]


def _count_degraded_services(metrics_snapshot):
    """Count services currently showing anomalous metrics."""
    if not metrics_snapshot:
        return 0
    degraded = 0
    for svc, m in metrics_snapshot.items():
        # Simple heuristic: error_rate > 0.1 or p99 > 1000ms
        if m.get("error_rate", 0) > 0.1 or m.get("p99_latency", 0) > 1000:
            degraded += 1
    return degraded


def _estimate_affected_users(target_service, dependents):
    """
    Estimate % of user traffic affected based on target + its callers.
    Uses conservative max (not sum) to avoid >100%.
    """
    affected = set([target_service] + dependents)
    return max(USER_TRAFFIC_PCT.get(s, 0) for s in affected)


def _score_risk(blast_score, system_health_pct, current_load_ratio):
    """
    Returns: 'LOW' | 'MEDIUM' | 'HIGH'
    blast_score:        0–5 (number of affected services)
    system_health_pct:  0–100
    current_load_ratio: current_rps / baseline_rps
    """
    risk_points = 0
    if blast_score >= 3:
        risk_points += 2
    elif blast_score >= 1:
        risk_points += 1

    if system_health_pct < 80:
        risk_points += 2
    elif system_health_pct < 95:
        risk_points += 1

    if current_load_ratio > 1.5:
        risk_points += 2
    elif current_load_ratio > 1.2:
        risk_points += 1

    if risk_points >= 4:
        return "HIGH"
    elif risk_points >= 2:
        return "MEDIUM"
    return "LOW"


def run_preflight(
    target_service: str,
    failure_type: str,
    metrics_snapshot: dict = None,
    dry_run: bool = False,
) -> dict:
    """
    Run pre-injection blast radius analysis.

    Returns:
    {
        "target": str,
        "failure_type": str,
        "dependents": [...],
        "blast_score": int,
        "estimated_affected_users_pct": int,
        "system_health_pct": float,
        "current_load_ratio": float,
        "degraded_services_count": int,
        "injection_risk": "LOW|MEDIUM|HIGH",
        "go_nogo": "GO|NO-GO",
        "nogo_reason": str | None,
        "sla_target_seconds": int,
        "business_impact_weight": int,
        "evaluated_at": str,
        "dry_run": bool
    }
    """
    dependents = _get_dependents(target_service)
    blast_score = len(dependents)

    degraded_count = _count_degraded_services(metrics_snapshot)

    # Compute system health %
    total_services = len(DEPENDENCY_GRAPH)
    system_health_pct = round(
        ((total_services - degraded_count) / total_services) * 100, 1
    )

    # Compute current load ratio
    current_load_ratio = 1.0
    if metrics_snapshot and target_service in metrics_snapshot:
        # Fallback: treat any rps > 0 as baseline proxy
        rps = metrics_snapshot[target_service].get("http_request_rate", 0)
        baseline_rps = {"api-gateway": 50, "order-service": 15,
                        "payment-service": 12, "product-service": 35,
                        "notification-service": 7}.get(target_service, 10)
        current_load_ratio = round(rps / baseline_rps if baseline_rps else 1.0, 2)

    affected_users_pct = _estimate_affected_users(target_service, dependents)
    risk = _score_risk(blast_score, system_health_pct, current_load_ratio)

    # GO/NO-GO logic
    go_nogo = "GO"
    nogo_reason = None

    if risk == "HIGH" and degraded_count >= 2:
        go_nogo = "NO-GO"
        nogo_reason = (
            f"{degraded_count} services already degraded and blast radius is HIGH. "
            f"Injection deferred to protect system stability."
        )
    elif risk == "HIGH" and current_load_ratio > 1.8:
        go_nogo = "NO-GO"
        nogo_reason = (
            f"System under {current_load_ratio:.1f}x elevated load. "
            f"Injection deferred — risk of unrecoverable cascade."
        )
    elif dry_run:
        go_nogo = "DRY-RUN"

    result = {
        "target": target_service,
        "failure_type": failure_type,
        "dependents": dependents,
        "blast_score": blast_score,
        "estimated_affected_users_pct": affected_users_pct,
        "system_health_pct": system_health_pct,
        "current_load_ratio": current_load_ratio,
        "degraded_services_count": degraded_count,
        "injection_risk": risk,
        "go_nogo": go_nogo,
        "nogo_reason": nogo_reason,
        "sla_target_seconds": SLA_TARGETS.get(failure_type, 60),
        "business_impact_weight": BUSINESS_IMPACT.get(target_service, 5),
        "evaluated_at": datetime.utcnow().isoformat(),
        "dry_run": dry_run,
    }

    _log_preflight(result)
    return result


def _log_preflight(result):
    """Append preflight result to logs/preflight_log.jsonl."""
    log_dir = os.path.join(os.path.dirname(__file__), "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, "preflight_log.jsonl")
    with open(log_path, "a") as f:
        f.write(json.dumps(result) + "\n")

    icon = "✅" if result["go_nogo"] == "GO" else "🛑"
    print(
        f"[preflight] {icon} {result['go_nogo']} | "
        f"target={result['target']} | "
        f"risk={result['injection_risk']} | "
        f"blast_score={result['blast_score']} | "
        f"affected_users={result['estimated_affected_users_pct']}% | "
        f"system_health={result['system_health_pct']}%"
    )
    if result["nogo_reason"]:
        print(f"[preflight] NO-GO reason: {result['nogo_reason']}")
