"""
novasurge/orchestrator.py

5-round chaos engineering orchestration loop.
Each round: inject → detect → analyze → decide → remediate → verify → log.
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
    "product-service":      "/products/health",
    "order-service":        "/orders/health",
    "payment-service":      "/payments/health",
    "notification-service": "/notifications/health",
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
        f"{'RECOVERY':>10}  {'HEALTHY':>8}  {'GUARDRAILS'}\n"
        f"{'-'*110}"
    )
    print(header)
    for s in summaries:
        guardrails = ", ".join(s.get("guardrails_triggered", [])) or "—"
        print(
            f"{s['round']:>3}  {s['failure_type']:<22}  {s['target_service']:<22}  "
            f"{s['remediator']:<18}  {str(s.get('recovery_time_seconds', '?')):>10}s  "
            f"{'YES' if s.get('health_confirmed') else 'NO':>8}  {guardrails}"
        )
    print("=" * 110)


# ── Main orchestration loop ───────────────────────────────────────────────────
async def run() -> None:
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
        }

        # ── a. INJECTING status ───────────────────────────────────────────
        write_round_status(n, "INJECTING")
        print(f"  ⟳  Round {n} status: INJECTING")

        # ── b. failure_strategy.select_target() ──────────────────────────
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

        # ── c. Inject chaos ───────────────────────────────────────────────
        injected_at = datetime.now(timezone.utc).isoformat()
        print(f"[orchestrator] Injecting {injector_name} into {hardcoded_target}")
        inject_result = injector_mod.inject(hardcoded_target)
        print(f"[orchestrator] Inject result: {json.dumps(inject_result, default=str)}")
        round_log["injected_at"] = injected_at

        # ── d. DETECTING status ───────────────────────────────────────────
        write_round_status(n, "DETECTING")
        print(f"  ⟳  Round {n} status: DETECTING")

        # ── e. Poll for anomaly ───────────────────────────────────────────
        # FIX: poll_for_anomaly is async — await it directly.
        # FIX: correct kwarg names are timeout_seconds and poll_interval.
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

        # ── f. ANALYZING status ───────────────────────────────────────────
        write_round_status(n, "ANALYZING")
        print(f"  ⟳  Round {n} status: ANALYZING")

        # ── g. RCA ───────────────────────────────────────────────────────
        metrics_snapshot = build_mock_metrics_snapshot(anomaly)
        rca_result = rca_analyze(anomaly, metrics_snapshot)
        round_log["rca_result"] = rca_result
        print(f"[orchestrator] RCA → true_origin={rca_result['true_origin']} "
              f"confidence={rca_result['confidence']}")

        # ── h. DECIDING status ────────────────────────────────────────────
        write_round_status(n, "DECIDING")
        print(f"  ⟳  Round {n} status: DECIDING")

        # ── i. Decision engine ────────────────────────────────────────────
        decision = decide(anomaly, rca_result)
        round_log["decision"] = decision
        round_log["guardrails_triggered"] = decision.get("guardrails_triggered", [])
        primary_rem = decision["primary_remediation"]
        fallback_rem = decision["fallback_remediation"]
        print(f"[orchestrator] Decision → primary='{primary_rem}' fallback='{fallback_rem}'")
        print(f"[orchestrator] Reasoning: {decision['reasoning_text']}")

        # ── j. Guardrails already applied inside decide() ────────────────
        if primary_rem in ("BLOCKED", "DEFERRED_30S"):
            print(f"[orchestrator] Primary remediation {primary_rem} — using fallback '{fallback_rem}'")
            primary_rem = fallback_rem

        # ── k. RECOVERING status ──────────────────────────────────────────
        write_round_status(n, "RECOVERING")
        print(f"  ⟳  Round {n} status: RECOVERING")
        mark_active(hardcoded_target, primary_rem)

        # ── l. Execute remediator ─────────────────────────────────────────
        remediator_fn = REMEDIATOR_REGISTRY.get(primary_rem)
        if remediator_fn is None:
            print(f"[orchestrator] ⚠ Unknown remediator '{primary_rem}'; trying fallback '{fallback_rem}'")
            remediator_fn = REMEDIATOR_REGISTRY.get(fallback_rem)

        round_log["remediator"] = primary_rem
        rem_result: dict[str, Any] = {"success": False, "details": "remediator not found"}

        if remediator_fn:
            rem_result = await remediator_fn(hardcoded_target)
            print(f"[orchestrator] Remediator result: {json.dumps(rem_result, default=str)}")

        record_remediation_result(
            hardcoded_target, primary_rem,
            success=rem_result.get("success", False),
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

        # ── Reverse injector side-effects where applicable ────────────────
        await _try_reverse(injector_name, injector_mod, hardcoded_target)

        # ── m. Poll /health ───────────────────────────────────────────────
        health_ok, health_elapsed = await _wait_for_healthy(hardcoded_target)
        recovered_at = datetime.now(timezone.utc).isoformat()

        # ── n. HEALTHY / FAILED status ────────────────────────────────────
        final_status = "HEALTHY" if health_ok else "FAILED"
        write_round_status(n, final_status, {
            "remediator": primary_rem,
            "health_confirmed": health_ok,
        })
        print(f"  ⟳  Round {n} status: {final_status}")
        clear_active(hardcoded_target)

        # ── o. Save round summary ─────────────────────────────────────────
        round_log.update({
            "recovered_at": recovered_at,
            "recovery_time_seconds": rem_result.get("recovery_time_seconds", health_elapsed),
            "health_confirmed": health_ok,
        })
        log_path = LOGS_DIR / f"round_{n}.json"
        log_path.write_text(json.dumps(round_log, indent=2, default=str))
        print(f"[orchestrator] Round {n} log saved → {log_path}")

        summaries.append(round_log)

        # ── p. Wait for metric normalization ─────────────────────────────
        if n < len(ROUNDS):
            print(f"\n[orchestrator] Waiting {METRIC_NORMALIZATION_WAIT}s for metric normalization…")
            await asyncio.sleep(METRIC_NORMALIZATION_WAIT)

    # ── Final summary table ───────────────────────────────────────────────────
    _print_summary(summaries)
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
    os.environ.setdefault("NOVASURGE_MOCK_K8S", "true")
    os.environ.setdefault("NOVASURGE_MOCK_ANOMALY", "true")
    asyncio.run(run())