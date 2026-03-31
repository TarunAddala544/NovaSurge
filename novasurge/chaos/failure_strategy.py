"""
novasurge/chaos/failure_strategy.py

Selects the highest-impact service to inject chaos into, using:
  blast_radius_score = number of downstream dependents
  current_load_score = current_http_request_rate / baseline_request_rate
  redundancy_score   = 1 / current_replica_count
  total_score        = (blast_radius * 0.5) + (current_load * 0.3) + (redundancy * 0.2)
"""

from __future__ import annotations

import json
from typing import Any

# Reuse dependency graph from rca
from novasurge.rca import DEPENDENCY_GRAPH

# Baseline request rate per service (requests/s) — tuned for shopfusion load gen
BASELINE_REQUEST_RATE: dict[str, float] = {
    "api-gateway":          50.0,
    "product-service":      35.0,
    "order-service":        22.0,
    "payment-service":      15.0,
    "notification-service":  5.0,
}

# Pre-compute blast radius (number of services that depend on each service)
def _compute_blast_radii() -> dict[str, int]:
    radius: dict[str, int] = {s: 0 for s in DEPENDENCY_GRAPH}
    for caller, callees in DEPENDENCY_GRAPH.items():
        for callee in callees:
            radius[callee] = radius.get(callee, 0) + 1
    return radius

BLAST_RADIUS: dict[str, int] = _compute_blast_radii()
MAX_BLAST_RADIUS = max(BLAST_RADIUS.values()) if BLAST_RADIUS else 1


def select_target(
    available_services: list[str],
    metrics_snapshot: dict[str, Any],
) -> str:
    """
    Score each available service and return the highest-scoring one.
    Logs a full scoring breakdown.

    Parameters
    ----------
    available_services : list of service names eligible for chaos injection
    metrics_snapshot   : dict[service -> {http_request_rate, replica_count, …}]

    Returns
    -------
    str — the service name to target
    """
    scores: dict[str, dict[str, float]] = {}

    for svc in available_services:
        m = metrics_snapshot.get(svc, {})

        # ── Blast radius (0-1 normalised) ──────────────────────────────────
        raw_blast = BLAST_RADIUS.get(svc, 0)
        blast_score = raw_blast / max(MAX_BLAST_RADIUS, 1)

        # ── Load score ─────────────────────────────────────────────────────
        current_rate = m.get("http_request_rate", BASELINE_REQUEST_RATE.get(svc, 10.0))
        baseline = BASELINE_REQUEST_RATE.get(svc, 10.0)
        load_score = min(current_rate / max(baseline, 1.0), 2.0) / 2.0  # cap at 1.0

        # ── Redundancy score ───────────────────────────────────────────────
        replicas = max(m.get("replica_count", 2), 1)
        redundancy_score = 1.0 / replicas  # 1 replica → 1.0, 3 replicas → 0.33

        # ── Weighted total ─────────────────────────────────────────────────
        total = (blast_score * 0.5) + (load_score * 0.3) + (redundancy_score * 0.2)

        scores[svc] = {
            "blast_radius_raw": raw_blast,
            "blast_radius_score": round(blast_score, 4),
            "current_rate": current_rate,
            "baseline_rate": baseline,
            "load_score": round(load_score, 4),
            "replica_count": replicas,
            "redundancy_score": round(redundancy_score, 4),
            "total_score": round(total, 4),
        }

    # ── Log scoring breakdown ──────────────────────────────────────────────
    print("[failure_strategy] Scoring breakdown:")
    for svc, s in sorted(scores.items(), key=lambda x: -x[1]["total_score"]):
        print(
            f"  {svc:30s}  blast={s['blast_radius_score']:.3f}  "
            f"load={s['load_score']:.3f}  redundancy={s['redundancy_score']:.3f}  "
            f"→ TOTAL={s['total_score']:.4f}"
        )

    if not scores:
        raise ValueError("select_target: no available services to score")

    winner = max(scores, key=lambda s: scores[s]["total_score"])
    print(f"[failure_strategy] Selected target: {winner} (score={scores[winner]['total_score']:.4f})")
    return winner


# ── Standalone test ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    sample_metrics = {
        "api-gateway":          {"http_request_rate": 52.0, "replica_count": 2},
        "product-service":      {"http_request_rate": 38.0, "replica_count": 3},
        "order-service":        {"http_request_rate": 25.0, "replica_count": 2},
        "payment-service":      {"http_request_rate": 14.0, "replica_count": 1},
        "notification-service": {"http_request_rate":  4.5, "replica_count": 2},
    }
    services = list(sample_metrics.keys())
    target = select_target(services, sample_metrics)
    print(f"\nFinal target: {target}")
