"""
sla_tracker.py — SLA tracking and resilience scoring for NovaSurge.
Called after every round completes in orchestrator.py.
Generates coverage_report.json after all rounds finish.
"""

import json
import os
from datetime import datetime

# SLA targets per failure type (seconds)
SLA_TARGETS = {
    "pod_deletion":      30,
    "cpu_throttle":      45,
    "network_partition": 60,
    "latency_injection": 40,
    "replica_reduction": 50,
}

# Detection time targets (seconds from injection to anomaly_confirmed)
DETECTION_SLA = {
    "pod_deletion":      15,
    "cpu_throttle":      20,
    "network_partition": 25,
    "latency_injection": 20,
    "replica_reduction": 30,
}

LOGS_DIR = os.path.join(os.path.dirname(__file__), "logs")
os.makedirs(LOGS_DIR, exist_ok=True)


def evaluate_round_sla(round_summary: dict) -> dict:
    """
    Evaluate SLA for a single completed round.
    Adds sla_result block to round_summary and returns it.

    round_summary must contain:
      failure_type, recovery_time_seconds,
      injected_at, anomaly_confirmed_at (ISO8601 strings)
    """
    failure_type = round_summary.get("failure_type", "unknown")
    recovery_seconds = round_summary.get("recovery_time_seconds")

    recovery_target = SLA_TARGETS.get(failure_type, 60)
    detection_target = DETECTION_SLA.get(failure_type, 30)

    # Detection time
    detection_seconds = None
    try:
        t_inject = datetime.fromisoformat(round_summary["injected_at"])
        t_detect = datetime.fromisoformat(round_summary["anomaly_confirmed_at"])
        detection_seconds = (t_detect - t_inject).total_seconds()
    except (KeyError, TypeError, ValueError):
        pass

    recovery_met = (
        recovery_seconds is not None and recovery_seconds <= recovery_target
    )
    detection_met = (
        detection_seconds is not None and detection_seconds <= detection_target
    )

    sla_result = {
        "recovery_target_seconds": recovery_target,
        "recovery_actual_seconds": round(recovery_seconds, 2) if recovery_seconds else None,
        "recovery_met": recovery_met,
        "recovery_margin_seconds": (
            round(recovery_target - recovery_seconds, 2)
            if recovery_seconds is not None else None
        ),
        "detection_target_seconds": detection_target,
        "detection_actual_seconds": round(detection_seconds, 2) if detection_seconds else None,
        "detection_met": detection_met,
        "both_met": recovery_met and detection_met,
    }

    _print_sla_result(round_summary.get("round", "?"), failure_type, sla_result)
    return sla_result


def _print_sla_result(round_num, failure_type, sla):
    icon = "✅" if sla["both_met"] else ("⚠️" if sla["recovery_met"] else "❌")
    print(
        f"[sla] Round {round_num} | {failure_type} | {icon} "
        f"Recovery: {sla['recovery_actual_seconds']}s "
        f"(target {sla['recovery_target_seconds']}s) | "
        f"Detection: {sla['detection_actual_seconds']}s "
        f"(target {sla['detection_target_seconds']}s)"
    )


def compute_resilience_score(round_summaries: list) -> float:
    """
    Compute a 0–100 resilience score across all completed rounds.

    Formula (weighted):
      40pts — SLA met rate  (recovery within target)
      25pts — Detection speed (avg detection vs target)
      20pts — Remediation success rate
      15pts — Guardrail effectiveness (guardrails that prevented cascade)

    Returns float 0.0–100.0
    """
    if not round_summaries:
        return 0.0

    completed = [r for r in round_summaries if r.get("recovery_time_seconds")]
    if not completed:
        return 0.0

    # 40pts: SLA met rate
    sla_met = sum(
        1 for r in completed
        if r.get("sla_result", {}).get("recovery_met", False)
    )
    sla_score = (sla_met / len(completed)) * 40

    # 25pts: Detection speed (how far under target on average)
    detection_ratios = []
    for r in completed:
        sla = r.get("sla_result", {})
        actual = sla.get("detection_actual_seconds")
        target = sla.get("detection_target_seconds")
        if actual is not None and target:
            # ratio < 1 means detected faster than target
            detection_ratios.append(min(actual / target, 2.0))
    if detection_ratios:
        avg_ratio = sum(detection_ratios) / len(detection_ratios)
        # ratio=0.5 → full 25pts; ratio=1.0 → 15pts; ratio=2.0 → 0pts
        detection_score = max(0, 25 * (1 - (avg_ratio - 0.5)))
    else:
        detection_score = 12.5  # neutral

    # 20pts: Remediation success (rounds that reached HEALTHY)
    successful = sum(
        1 for r in completed
        if r.get("status") == "HEALTHY"
    )
    remediation_score = (successful / len(completed)) * 20

    # 15pts: Guardrail effectiveness
    # Give 3pts per round where guardrails fired correctly (not 0 not excessive)
    guardrail_score = 0
    for r in completed:
        triggered = r.get("guardrails_triggered", [])
        if isinstance(triggered, str):
            try:
                triggered = json.loads(triggered)
            except Exception:
                triggered = []
        if 0 < len(triggered) <= 2:
            guardrail_score += 3
    guardrail_score = min(guardrail_score, 15)

    total = round(sla_score + detection_score + remediation_score + guardrail_score, 1)
    return min(total, 100.0)


def generate_coverage_report(round_summaries: list) -> dict:
    """
    Generate final coverage_report.json after all rounds complete.
    Written to novasurge/logs/coverage_report.json.
    """
    completed = [r for r in round_summaries if r.get("recovery_time_seconds")]

    services_tested = list(set(r.get("target_service") for r in completed if r.get("target_service")))
    all_services = ["api-gateway", "product-service", "order-service",
                    "payment-service", "notification-service"]
    services_untested = [s for s in all_services if s not in services_tested]

    failure_types_covered = list(set(
        r.get("failure_type") for r in completed if r.get("failure_type")
    ))

    recovery_times = [r["recovery_time_seconds"] for r in completed if r.get("recovery_time_seconds")]
    detection_times = [
        r["sla_result"]["detection_actual_seconds"]
        for r in completed
        if r.get("sla_result", {}).get("detection_actual_seconds") is not None
    ]

    sla_met = sum(1 for r in completed if r.get("sla_result", {}).get("recovery_met"))

    total_guardrails = sum(
        len(json.loads(r["guardrails_triggered"])
            if isinstance(r.get("guardrails_triggered"), str)
            else (r.get("guardrails_triggered") or []))
        for r in completed
    )

    resilience_score = compute_resilience_score(round_summaries)

    report = {
        "generated_at": datetime.utcnow().isoformat(),
        "total_rounds": len(completed),
        "services_tested": services_tested,
        "services_untested": services_untested,
        "failure_types_covered": failure_types_covered,
        "successful_recoveries": sum(1 for r in completed if r.get("status") == "HEALTHY"),
        "sla_met_count": sla_met,
        "sla_breach_count": len(completed) - sla_met,
        "mean_ttr_seconds": round(sum(recovery_times) / len(recovery_times), 2) if recovery_times else None,
        "mean_ttd_seconds": round(sum(detection_times) / len(detection_times), 2) if detection_times else None,
        "min_recovery_seconds": round(min(recovery_times), 2) if recovery_times else None,
        "max_recovery_seconds": round(max(recovery_times), 2) if recovery_times else None,
        "guardrails_triggered_total": total_guardrails,
        "resilience_score": resilience_score,
        "score_breakdown": _score_breakdown_text(resilience_score),
    }

    out_path = os.path.join(LOGS_DIR, "coverage_report.json")
    with open(out_path, "w") as f:
        json.dump(report, f, indent=2)

    _print_coverage_report(report)
    return report


def _score_breakdown_text(score):
    if score >= 90:
        return "EXCELLENT — System demonstrated elite resilience across all scenarios."
    elif score >= 75:
        return "GOOD — System recovered reliably. Minor SLA misses detected."
    elif score >= 60:
        return "FAIR — Recovery functional but detection or speed needs tuning."
    else:
        return "NEEDS IMPROVEMENT — Multiple SLA breaches or recovery failures."


def _print_coverage_report(report):
    print("\n" + "=" * 60)
    print("  NOVASURGE RESILIENCE REPORT")
    print("=" * 60)
    print(f"  Resilience Score : {report['resilience_score']}/100")
    print(f"  Verdict          : {report['score_breakdown']}")
    print(f"  Rounds Complete  : {report['total_rounds']}")
    print(f"  SLA Met          : {report['sla_met_count']}/{report['total_rounds']}")
    print(f"  Mean TTD         : {report['mean_ttd_seconds']}s")
    print(f"  Mean TTR         : {report['mean_ttr_seconds']}s")
    print(f"  Guardrails Fired : {report['guardrails_triggered_total']}")
    print(f"  Services Untested: {report['services_untested'] or 'None'}")
    print("=" * 60 + "\n")
