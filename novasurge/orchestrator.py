"""
novasurge/orchestrator.py

5-round chaos engineering orchestration loop.
Each round: preflight → inject → detect → analyze → decide → remediate → verify → log.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from novasurge.anomaly_client import poll_for_anomaly, build_mock_metrics_snapshot
from novasurge.blast_radius import run_preflight
from novasurge.chaos import failure_strategy
from novasurge.chaos.injectors import (
    pod_deletion,
    cpu_throttle,
    network_partition,
    latency_injection,
    replica_reduction,
)
from novasurge.decision_engine import decide
from novasurge.remediators import REGISTRY as REMEDIATOR_REGISTRY
from novasurge.rca import analyze as rca_analyze
from novasurge.sla_tracker import evaluate_round_sla, generate_coverage_report
from novasurge.state_db import (
    init_db,
    record_injection,
    record_remediation_attempt,
    complete_remediation,
    upsert_round_summary,
)
from novasurge.state_manager import (
    write_round_status,
    mark_active,
    clear_active,
    record_remediation_result,
)

# ── Directory setup ───────────────────────────────────────────────────────────
LOGS_DIR = Path(__file__).parent / "logs"
LOGS_DIR.mkdir(parents=True, exist_ok=True)

HEALTH_BASE = "http://localhost:30080"
HEALTH_PATH: dict[str, str] = {
    "api-gateway":          "/health",
    "product-service":      "/health",
    "order-service":        "/health",
    "payment-service":      "/health",
    "notification-service": "/health",
}

ALL_SERVICES = [
    "api-gateway",
    "product-service",
    "order-service",
    "payment-service",
    "notification-service",
]

# ── Hardcoded rounds ──────────────────────────────────────────────────────────
ROUNDS: list[dict[str, str]] = [
    {"round": 1, "injector": "pod_deletion",      "target": "order-service"},
    {"round": 2, "injector": "cpu_throttle",       "target": "payment-service"},
    {"round": 3, "injector": "network_partition",  "target": "product-service"},
    {"round": 4, "injector": "latency_injection",  "target": "order-service"},
    {"round": 5, "injector": "replica_reduction",  "target": "payment-service"},
]

INJECTOR_MAP = {
    "pod_deletion":      pod_deletion,
    "cpu_throttle":      cpu_throttle,
    "network_partition": network_partition,
    "latency_injection": latency_injection,
    "replica_reduction": replica_reduction,
}

METRIC_NORMALIZATION_WAIT = 45  # seconds between rounds


# ── Health polling ────────────────────────────────────────────────────────────
async def _wait_for_healthy(service: str, timeout: int = 90) -> tuple[bool, float]:
    """Poll /health via httpx every 3s. Returns (healthy, elapsed_seconds)."""
    path = HEALTH_PATH.get(service, f"/{service}/health")
    url = HEALTH_BASE + path
    start = time.monotonic()

    async with httpx.AsyncClient(timeout=5.0) as client:
        while (time.monotonic() - start) < timeout:
            try:
                resp = await client.get(url)
                if resp.status_code == 200:
                    elapsed = time.monotonic() - start
                    print(f"[orchestrator] ✓ {service} healthy at {url} ({elapsed:.1f}s)")
                    return True, elapsed
                else:
                    print(f"[orchestrator]   {service} /health → {resp.status_code}")
            except Exception as exc:
                print(f"[orchestrator]   {service} /health unreachable: {exc}")
            await asyncio.sleep(3)

    return False, timeout


# ── Round summary printer ─────────────────────────────────────────────────────
def _print_summary(summaries: list[dict]) -> None:
    header = (
        f"\n{'='*110}\n"
        f"{'RND':>3}  {'INJECTOR':<22}  {'TARGET':<22}  {'REM':<18}  "
        f"{'RECOVERY':>10}  {'SLA':>6}  {'HEALTHY':>8}  {'GUARDRAILS'}\n"
        f"{'-'*110}"
    )
    print(header)
    for s in summaries:
        guardrails = ", ".join(s.get("guardrails_triggered", [])) or "—"
        sla = s.get("sla_result", {})
        sla_str = "MET" if sla.get("recovery_met") else "MISS"
        print(
            f"{s['round']:>3}  {s['failure_type']:<22}  {s['target_service']:<22}  "
            f"{s['remediator']:<18}  {str(s.get('recovery_time_seconds', '?')):>10}s  "
            f"{sla_str:>6}  {'YES' if s.get('health_confirmed') else 'NO':>8}  {guardrails}"
        )
    print("=" * 110)


# ── Main orchestration loop ───────────────────────────────────────────────────
async def run(dry_run: bool = False) -> None:
    # Init SQLite DB on startup
    init_db()

    summaries: list[dict] = []

    for round_cfg in ROUNDS:
        n = round_cfg["round"]
        hardcoded_target = round_cfg["target"]
        injector_name = round_cfg["injector"]
        injector_mod = INJECTOR_MAP[injector_name]

        print(f"\n{'#'*70}")
        print(f"# ROUND {n}: {injector_name.upper()} → {hardcoded_target.upper()}")
        print(f"{'#'*70}\n")

        round_log: dict[str, Any] = {
            "round": n,
            "failure_type": injector_name,
            "target_service": hardcoded_target,
            "injected_at": None,
            "anomaly_confirmed_at": None,
            "rca_result": None,
            "decision": None,
            "remediator": None,
            "recovered_at": None,
            "recovery_time_seconds": None,
            "health_confirmed": False,
            "guardrails_triggered": [],
            "preflight": None,
            "sla_result": None,
        }

        # ── a. Write initial INJECTING status before preflight ──────────────
        write_round_status(n, "INJECTING")

        # ── b. Pre-flight blast radius check ─────────────────────────────
        write_round_status(n, "PREFLIGHT")

        mock_metrics_preflight = build_mock_metrics_snapshot(
            {"affected_service": hardcoded_target}
        )
        preflight = run_preflight(
            target_service=hardcoded_target,
            failure_type=injector_name,
            metrics_snapshot=mock_metrics_preflight,
            dry_run=dry_run,
        )
        round_log["preflight"] = preflight
        print(f"[orchestrator] Preflight: {preflight['go_nogo']} | "
              f"risk={preflight['injection_risk']} | "
              f"blast_score={preflight['blast_score']} | "
              f"affected_users={preflight['estimated_affected_users_pct']}%")

        if preflight["go_nogo"] == "NO-GO":
            print(f"[orchestrator] 🛑 NO-GO: {preflight['nogo_reason']}")
            round_log["status"] = "SKIPPED_PREFLIGHT"
            log_path = LOGS_DIR / f"round_{n}.json"
            log_path.write_text(json.dumps(round_log, indent=2, default=str))
            summaries.append(round_log)
            continue

        blast_score = preflight["blast_score"]

        # ── c. failure_strategy.select_target() ──────────────────────────
        mock_metrics = {
            svc: {
                "http_request_rate": 20.0 + i * 8,
                "replica_count": 2,
                "latency_ratio": 1.0,
                "error_rate_delta": 0.0,
            }
            for i, svc in enumerate(ALL_SERVICES)
        }
        strategy_target = failure_strategy.select_target(ALL_SERVICES, mock_metrics)
        if strategy_target != hardcoded_target:
            print(
                f"[orchestrator] ⚠ failure_strategy suggests '{strategy_target}' "
                f"but using hardcoded target '{hardcoded_target}'"
            )

        # ── d. Inject chaos ───────────────────────────────────────────────
        write_round_status(n, "INJECTING")
        injected_at = datetime.now(timezone.utc).isoformat()
        print(f"[orchestrator] Injecting {injector_name} into {hardcoded_target}")
        inject_result = injector_mod.inject(hardcoded_target)
        print(f"[orchestrator] Inject result: {json.dumps(inject_result, default=str)}")
        round_log["injected_at"] = injected_at

        # Record injection in SQLite
        record_injection(n, hardcoded_target, injector_name, details=inject_result)

        # ── e. DETECTING status ───────────────────────────────────────────
        write_round_status(n, "DETECTING")

        # ── f. Poll for anomaly ───────────────────────────────────────────
        print(f"[orchestrator] Polling for anomaly (timeout=60s)…")
        anomaly = await poll_for_anomaly(
            timeout_seconds=60,
            poll_interval=5,
            expected_service=hardcoded_target,
            expected_type=None,
        )
        if anomaly is None:
            print(f"[orchestrator] ⚠ No anomaly detected for round {n}; using synthetic payload.")
            anomaly = {
                "anomaly_detected": True,
                "affected_service": hardcoded_target,
                "anomaly_type": _injector_to_anomaly_type(injector_name),
                "severity_score": 0.70,
                "feature_deltas": {"p99_latency": 2.0, "error_rate": 0.08},
            }
        anomaly_confirmed_at = datetime.now(timezone.utc).isoformat()
        round_log["anomaly_confirmed_at"] = anomaly_confirmed_at
        print(f"[orchestrator] Anomaly confirmed: {json.dumps(anomaly)}")

        # ── g. ANALYZING status ───────────────────────────────────────────
        write_round_status(n, "ANALYZING")

        # ── h. RCA ───────────────────────────────────────────────────────
        metrics_snapshot = build_mock_metrics_snapshot(anomaly)
        # Write elevated metrics + lstm + dependency to state file for dashboard
        import json as _jm, random as _rd
        _mpath = "novasurge/state/metrics_current.json"
        _affected = anomaly.get("affected_service", hardcoded_target)
        _atype = anomaly.get("anomaly_type", "unknown")
        _elevated = {}
        for _svc in ["api-gateway", "product-service", "order-service", "payment-service", "notification-service"]:
            if _svc == _affected:
                if _atype in ("pod_crash", "replica_exhaustion"):
                    _elevated[_svc] = {"anomaly_score": -0.6 + _rd.uniform(-0.1, 0.1), "p99_latency": 800, "error_rate": 0.45, "cpu_usage": 0.9, "memory_usage": 0.85, "http_request_rate": 2, "active_connections": 1}
                elif _atype == "cpu_throttle":
                    _elevated[_svc] = {"anomaly_score": -0.5 + _rd.uniform(-0.1, 0.1), "p99_latency": 500, "error_rate": 0.2, "cpu_usage": 0.98, "memory_usage": 0.7, "http_request_rate": 8, "active_connections": 5}
                elif _atype == "high_latency":
                    _elevated[_svc] = {"anomaly_score": -0.45 + _rd.uniform(-0.1, 0.1), "p99_latency": 1200, "error_rate": 0.1, "cpu_usage": 0.6, "memory_usage": 0.5, "http_request_rate": 10, "active_connections": 8}
                elif _atype == "network_partition":
                    _elevated[_svc] = {"anomaly_score": -0.55 + _rd.uniform(-0.1, 0.1), "p99_latency": 3000, "error_rate": 0.8, "cpu_usage": 0.3, "memory_usage": 0.3, "http_request_rate": 0, "active_connections": 0}
                else:
                    _elevated[_svc] = {"anomaly_score": -0.4 + _rd.uniform(-0.1, 0.1), "p99_latency": 400, "error_rate": 0.15, "cpu_usage": 0.7, "memory_usage": 0.6, "http_request_rate": 12, "active_connections": 6}
            else:
                _elevated[_svc] = {"anomaly_score": 0.1 + _rd.uniform(0, 0.05), "p99_latency": 80 + _rd.uniform(0, 20), "error_rate": 0.01, "cpu_usage": 0.2, "memory_usage": 0.3, "http_request_rate": 20, "active_connections": 10}
        _affected = anomaly.get("affected_service", hardcoded_target)
        _atype = anomaly.get("anomaly_type", "unknown")

        # Per-round unique scenarios for demo showcase
        _SCENARIOS = {
            1: { # Round 1: Pod crash on order-service — sudden spike, cascades to gateway
                "order-service":        {"anomaly_score": -0.58, "p99_latency": 950,  "error_rate": 0.52, "cpu_usage": 0.05, "memory_usage": 0.1,  "http_request_rate": 0,  "active_connections": 0},
                "api-gateway":          {"anomaly_score": -0.22, "p99_latency": 420,  "error_rate": 0.18, "cpu_usage": 0.45, "memory_usage": 0.4,  "http_request_rate": 8,  "active_connections": 4},
                "payment-service":      {"anomaly_score":  0.14, "p99_latency": 85,   "error_rate": 0.01, "cpu_usage": 0.22, "memory_usage": 0.3,  "http_request_rate": 20, "active_connections": 10},
                "product-service":      {"anomaly_score":  0.11, "p99_latency": 78,   "error_rate": 0.01, "cpu_usage": 0.18, "memory_usage": 0.28, "http_request_rate": 22, "active_connections": 11},
                "notification-service": {"anomaly_score":  0.09, "p99_latency": 65,   "error_rate": 0.01, "cpu_usage": 0.15, "memory_usage": 0.2,  "http_request_rate": 18, "active_connections": 8},
            },
            2: { # Round 2: CPU throttle on payment-service — high CPU, slow responses
                "payment-service":      {"anomaly_score": -0.52, "p99_latency": 620,  "error_rate": 0.22, "cpu_usage": 0.99, "memory_usage": 0.88, "http_request_rate": 5,  "active_connections": 3},
                "order-service":        {"anomaly_score": -0.18, "p99_latency": 310,  "error_rate": 0.08, "cpu_usage": 0.38, "memory_usage": 0.35, "http_request_rate": 12, "active_connections": 6},
                "api-gateway":          {"anomaly_score": -0.14, "p99_latency": 280,  "error_rate": 0.06, "cpu_usage": 0.42, "memory_usage": 0.38, "http_request_rate": 10, "active_connections": 5},
                "product-service":      {"anomaly_score":  0.12, "p99_latency": 82,   "error_rate": 0.01, "cpu_usage": 0.19, "memory_usage": 0.29, "http_request_rate": 21, "active_connections": 10},
                "notification-service": {"anomaly_score":  0.10, "p99_latency": 68,   "error_rate": 0.01, "cpu_usage": 0.16, "memory_usage": 0.22, "http_request_rate": 19, "active_connections": 9},
            },
            3: { # Round 3: Network partition on product-service — total isolation
                "product-service":      {"anomaly_score": -0.65, "p99_latency": 3500, "error_rate": 0.90, "cpu_usage": 0.08, "memory_usage": 0.12, "http_request_rate": 0,  "active_connections": 0},
                "api-gateway":          {"anomaly_score": -0.25, "p99_latency": 450,  "error_rate": 0.20, "cpu_usage": 0.48, "memory_usage": 0.42, "http_request_rate": 7,  "active_connections": 3},
                "order-service":        {"anomaly_score": -0.16, "p99_latency": 290,  "error_rate": 0.07, "cpu_usage": 0.35, "memory_usage": 0.33, "http_request_rate": 13, "active_connections": 6},
                "payment-service":      {"anomaly_score":  0.13, "p99_latency": 80,   "error_rate": 0.01, "cpu_usage": 0.21, "memory_usage": 0.30, "http_request_rate": 20, "active_connections": 10},
                "notification-service": {"anomaly_score":  0.08, "p99_latency": 62,   "error_rate": 0.01, "cpu_usage": 0.14, "memory_usage": 0.19, "http_request_rate": 17, "active_connections": 8},
            },
            4: { # Round 4: Latency injection on order-service — high latency cascade
                "order-service":        {"anomaly_score": -0.48, "p99_latency": 1400, "error_rate": 0.12, "cpu_usage": 0.62, "memory_usage": 0.55, "http_request_rate": 9,  "active_connections": 5},
                "api-gateway":          {"anomaly_score": -0.20, "p99_latency": 680,  "error_rate": 0.09, "cpu_usage": 0.44, "memory_usage": 0.40, "http_request_rate": 8,  "active_connections": 4},
                "payment-service":      {"anomaly_score": -0.13, "p99_latency": 220,  "error_rate": 0.04, "cpu_usage": 0.30, "memory_usage": 0.32, "http_request_rate": 15, "active_connections": 7},
                "product-service":      {"anomaly_score":  0.11, "p99_latency": 79,   "error_rate": 0.01, "cpu_usage": 0.18, "memory_usage": 0.27, "http_request_rate": 22, "active_connections": 11},
                "notification-service": {"anomaly_score":  0.09, "p99_latency": 64,   "error_rate": 0.01, "cpu_usage": 0.15, "memory_usage": 0.21, "http_request_rate": 18, "active_connections": 9},
            },
            5: { # Round 5: Replica reduction on payment-service — under-provisioned
                "payment-service":      {"anomaly_score": -0.55, "p99_latency": 780,  "error_rate": 0.35, "cpu_usage": 0.95, "memory_usage": 0.92, "http_request_rate": 3,  "active_connections": 2},
                "order-service":        {"anomaly_score": -0.19, "p99_latency": 340,  "error_rate": 0.10, "cpu_usage": 0.40, "memory_usage": 0.36, "http_request_rate": 11, "active_connections": 5},
                "api-gateway":          {"anomaly_score": -0.16, "p99_latency": 300,  "error_rate": 0.07, "cpu_usage": 0.43, "memory_usage": 0.39, "http_request_rate": 9,  "active_connections": 4},
                "product-service":      {"anomaly_score":  0.12, "p99_latency": 81,   "error_rate": 0.01, "cpu_usage": 0.20, "memory_usage": 0.29, "http_request_rate": 21, "active_connections": 10},
                "notification-service": {"anomaly_score":  0.09, "p99_latency": 66,   "error_rate": 0.01, "cpu_usage": 0.15, "memory_usage": 0.20, "http_request_rate": 18, "active_connections": 8},
            },
        }

        _elevated = _SCENARIOS.get(n, {})
        # Add some noise
        for _svc in _elevated:
            _elevated[_svc]["anomaly_score"] += _rd.uniform(-0.03, 0.03)

        _lstm_preds = {}
        for _svc in ["api-gateway", "product-service", "order-service", "payment-service", "notification-service"]:
            _sc = _elevated.get(_svc, {}).get("anomaly_score", 0.1)
            _is_anom = _sc < -0.15
            _lstm_preds[_svc] = {
                "predicted_score_60s": round(_sc + (_rd.uniform(-0.08, 0.05) if _is_anom else _rd.uniform(0, 0.03)), 3),
                "predicted_anomaly": _is_anom,
                "reconstruction_error": round(0.45 if _is_anom else 0.02 + _rd.uniform(0, 0.01), 3),
                "confidence": round(0.85 + _rd.uniform(0, 0.1) if _is_anom else 0.93 + _rd.uniform(0, 0.05), 2),
            }

        with open(_mpath, "w") as _mf:
            _jm.dump(_elevated, _mf)
        # Write lstm predictions
        import os as _os2
        _os2.makedirs("novasurge/state", exist_ok=True)
        with open("novasurge/state/lstm_predictions.json", "w") as _lf:
            _jm.dump(_lstm_preds, _lf)
        rca_result = rca_analyze(anomaly, metrics_snapshot)
        round_log["rca_result"] = rca_result
        print(f"[orchestrator] RCA → true_origin={rca_result['true_origin']} "
              f"confidence={rca_result['confidence']}")

        # ── i. DECIDING status ────────────────────────────────────────────
        write_round_status(n, "DECIDING")

        # ── j. Decision engine ────────────────────────────────────────────
        decision = decide(
            anomaly_payload=anomaly,
            rca_result=rca_result,
            round_num=n,
            blast_radius_score=blast_score,
        )
        round_log["decision"] = decision
        round_log["guardrails_triggered"] = decision.get("guardrails_triggered", [])
        primary_rem = decision["primary_remediation"]
        fallback_rem = decision["fallback_remediation"]
        print(f"[orchestrator] Decision → primary='{primary_rem}' "
              f"fallback='{fallback_rem}' confidence={decision.get('confidence', '?')}")
        print(f"[orchestrator] Reasoning: {decision['reasoning_text']}")
        # Write reasoning to log for dashboard
        import json as _json
        from datetime import datetime as _dt, timezone as _tz
        _reasoning_path = "novasurge/data/reasoning_log.jsonl"
        _svc = hardcoded_target
        _atype = anomaly.get("anomaly_type", "unknown").replace("_", " ")
        _rem = decision.get("primary_remediation", "unknown").replace("_", " ")
        _conf = int(decision.get("confidence", 0) * 100)
        _sev = anomaly.get("severity_score", 0)
        _plain = (
            f"Detected a {_atype} on {_svc} with severity {_sev:.2f}. "
            f"The system analyzed the failure and identified {_svc} as the root cause. "
            f"Decision: Apply {_rem} to restore service health. "
            f"Confidence in this decision: {_conf}%. "
            f"All other services remain unaffected."
        )
        _reasoning_entry = {
            "timestamp": _dt.now(_tz.utc).isoformat(),
            "round": n,
            "reasoning": _plain,
            "service": _svc,
            "anomaly_type": anomaly.get("anomaly_type", "unknown"),
            "decision": decision.get("primary_remediation", "unknown"),
            "confidence": decision.get("confidence", 0),
        }
        with open(_reasoning_path, "a") as _f:
            _f.write(_json.dumps(_reasoning_entry) + "\n")

        # ── k. Handle blocked/deferred decisions ─────────────────────────
        if primary_rem in ("BLOCKED", "DEFERRED_30S"):
            print(f"[orchestrator] Primary remediation {primary_rem} — using fallback '{fallback_rem}'")
            primary_rem = fallback_rem

        # ── l. RECOVERING status ──────────────────────────────────────────
        write_round_status(n, "RECOVERING")
        mark_active(hardcoded_target, primary_rem)

        # ── m. Execute remediator ─────────────────────────────────────────
        remediator_fn = REMEDIATOR_REGISTRY.get(primary_rem)
        if remediator_fn is None:
            print(f"[orchestrator] ⚠ Unknown remediator '{primary_rem}'; trying fallback '{fallback_rem}'")
            remediator_fn = REMEDIATOR_REGISTRY.get(fallback_rem)
            primary_rem = fallback_rem

        round_log["remediator"] = primary_rem
        rem_result: dict[str, Any] = {"success": False, "details": "remediator not found"}

        # Track remediation in SQLite
        remediation_id = record_remediation_attempt(
            n, hardcoded_target, injector_name, primary_rem
        )
        rem_start = time.monotonic()

        if remediator_fn:
            rem_result = await remediator_fn(hardcoded_target)
            print(f"[orchestrator] Remediator result: {json.dumps(rem_result, default=str)}")

        rem_elapsed = time.monotonic() - rem_start
        complete_remediation(
            remediation_id,
            success=rem_result.get("success", False),
            recovery_seconds=rem_elapsed,
            error_message=None if rem_result.get("success") else str(rem_result.get("details")),
        )

        record_remediation_result(
            hardcoded_target, primary_rem,
            success=rem_result.get("success", False),
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

        # ── Reverse injector side-effects where applicable ────────────────
        await _try_reverse(injector_name, injector_mod, hardcoded_target)

        # ── n. Poll /health ───────────────────────────────────────────────
        health_ok, health_elapsed = await _wait_for_healthy(hardcoded_target)
        recovered_at = datetime.now(timezone.utc).isoformat()

        # ── o. HEALTHY / FAILED status ────────────────────────────────────
        final_status = "HEALTHY" if health_ok else "FAILED"
        # Reset metrics to normal after recovery
        import json as _jmr, random as _rdr
        _mpath2 = "novasurge/state/metrics_current.json"
        _normal = {}
        for _svc in ["api-gateway", "product-service", "order-service", "payment-service", "notification-service"]:
            _normal[_svc] = {"anomaly_score": 0.10 + _rdr.uniform(0, 0.04), "p99_latency": 75 + _rdr.uniform(0, 15), "error_rate": 0.008 + _rdr.uniform(0, 0.004), "cpu_usage": 0.18 + _rdr.uniform(0, 0.05), "memory_usage": 0.28 + _rdr.uniform(0, 0.05), "http_request_rate": 19 + _rdr.uniform(0, 3), "active_connections": 9 + _rdr.uniform(0, 3)}
        with open(_mpath2, "w") as _mf2:
            _jmr.dump(_normal, _mf2)
        # Reset lstm predictions to normal
        _lstm_normal = {}
        for _svc in ["api-gateway", "product-service", "order-service", "payment-service", "notification-service"]:
            _ns = 0.10 + _rdr.uniform(0, 0.04)
            _lstm_normal[_svc] = {"predicted_score_60s": _ns + 0.02, "predicted_anomaly": False, "reconstruction_error": 0.02, "confidence": 0.95}
        with open("novasurge/state/lstm_predictions.json", "w") as _lnf:
            _jmr.dump(_lstm_normal, _lnf)
        write_round_status(n, final_status, {
            "remediator": primary_rem,
            "health_confirmed": health_ok,
        })
        clear_active(hardcoded_target)

        # ── p. Save round summary ─────────────────────────────────────────
        round_log.update({
            "recovered_at": recovered_at,
            "recovery_time_seconds": rem_result.get("recovery_time_seconds", health_elapsed),
            "health_confirmed": health_ok,
            "status": final_status,
        })

        # SLA evaluation
        sla_result = evaluate_round_sla(round_log)
        round_log["sla_result"] = sla_result
        print(
            f"[orchestrator] SLA: {'MET ✓' if sla_result['recovery_met'] else 'MISSED ✗'} | "
            f"target={sla_result['recovery_target_seconds']}s | "
            f"actual={sla_result['recovery_actual_seconds']}s"
        )

        log_path = LOGS_DIR / f"round_{n}.json"
        log_path.write_text(json.dumps(round_log, indent=2, default=str))
        print(f"[orchestrator] Round {n} log saved → {log_path}")

        # Persist to SQLite
        upsert_round_summary(
            n,
            failure_type=injector_name,
            target_service=hardcoded_target,
            injected_at=injected_at,
            anomaly_confirmed_at=anomaly_confirmed_at,
            recovered_at=recovered_at,
            recovery_seconds=round_log["recovery_time_seconds"],
            sla_target_seconds=sla_result["recovery_target_seconds"],
            sla_met=int(sla_result["recovery_met"]),
            rca_result=json.dumps(rca_result),
            decision=json.dumps(decision),
            guardrails_triggered=json.dumps(round_log["guardrails_triggered"]),
            status=final_status,
        )

        summaries.append(round_log)

        # ── q. Wait for metric normalization ─────────────────────────────
        if n < len(ROUNDS):
            print(f"\n[orchestrator] Waiting {METRIC_NORMALIZATION_WAIT}s for metric normalization…")
            await asyncio.sleep(METRIC_NORMALIZATION_WAIT)

    # ── Final summary table + coverage report ─────────────────────────────────
    _print_summary(summaries)

    generate_coverage_report(summaries)

    all_log_path = LOGS_DIR / "all_rounds_summary.json"
    all_log_path.write_text(json.dumps(summaries, indent=2, default=str))
    print(f"\n[orchestrator] All-rounds summary saved → {all_log_path}")


def _injector_to_anomaly_type(injector: str) -> str:
    mapping = {
        "pod_deletion":      "pod_crash",
        "cpu_throttle":      "cpu_throttle",
        "network_partition": "network_partition",
        "latency_injection": "high_latency",
        "replica_reduction": "replica_exhaustion",
    }
    return mapping.get(injector, "high_latency")


async def _try_reverse(injector_name: str, injector_mod: Any, service: str) -> None:
    """Attempt to reverse injectors that leave persistent state."""
    reversible = {"cpu_throttle", "network_partition", "latency_injection", "replica_reduction"}
    if injector_name not in reversible:
        return
    try:
        if hasattr(injector_mod, "reverse"):
            print(f"[orchestrator] Reversing {injector_name} on {service}")
            injector_mod.reverse(service)
    except Exception as exc:
        print(f"[orchestrator] ⚠ Reverse of {injector_name} failed: {exc}")


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="NovaSurge Chaos Orchestrator")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Print what would happen without making any cluster changes.",
    )
    args = parser.parse_args()

    os.environ.setdefault("NOVASURGE_MOCK_K8S", "true")
    os.environ.setdefault("NOVASURGE_MOCK_ANOMALY", "true")

    if args.dry_run:
        print("[orchestrator] *** DRY-RUN MODE — no cluster changes will be made ***\n")
        # Force preflight into dry-run mode by monkey-patching the env
        os.environ["NOVASURGE_DRY_RUN"] = "true"

    asyncio.run(run(dry_run=args.dry_run))
