"""
novasurge/reasoning.py

Generates human-readable reasoning text for anomaly detection and remediation.
Uses deterministic Python string templates - no LLM, fully offline.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

# ── Templates for Phase 1 (Detection + Decision) ───────────────────────────────

PHASE1_TEMPLATES: Dict[str, Dict[str, str]] = {
    "pod_crash": {
        "detection": "[{timestamp}] Anomaly confirmed on {service}. Pod crash detected with zero active connections and elevated error rate. Isolation Forest score: {score:.2f}.",
        "decision": "Root cause localized to {service} - no upstream dependencies showing deviation. Executing pod restart followed by HPA scale-out to ensure resilience.",
        "guardrail": "Guardrail triggered: {guardrail_reason}. Adjusting remediation plan to {new_action}.",
    },
    "oom_kill": {
        "detection": "[{timestamp}] Anomaly confirmed on {service}. Memory exhaustion detected - processes being killed by OOM killer. Isolation Forest score: {score:.2f}.",
        "decision": "Memory pressure identified on {service}. Executing HPA scale-out to distribute load, followed by pod restart to clear memory pressure.",
        "guardrail": "Guardrail triggered: {guardrail_reason}. Adjusting remediation plan to {new_action}.",
    },
    "cpu_throttle": {
        "detection": "[{timestamp}] Anomaly confirmed on {service}. CPU throttling detected - high CPU usage with normal traffic levels. Isolation Forest score: {score:.2f}.",
        "decision": "Resource exhaustion pattern identified on {service}. CPU bottleneck detected with traffic within normal bounds. Executing HPA scale-out to add capacity.",
        "guardrail": "Guardrail triggered: {guardrail_reason}. Adjusting remediation plan to {new_action}.",
    },
    "network_partition": {
        "detection": "[{timestamp}] Anomaly confirmed on {service}. Network partition detected - zero request rate reaching service. Isolation Forest score: {score:.2f}.",
        "decision": "Connectivity failure isolated to {service}. Upstream services unable to reach target. Executing traffic reroute to bypass affected node, followed by pod restart.",
        "guardrail": "Guardrail triggered: {guardrail_reason}. Adjusting remediation plan to {new_action}.",
    },
    "replica_exhaustion": {
        "detection": "[{timestamp}] Anomaly confirmed on {service}. Replica exhaustion detected - all metrics depressed below baseline. Isolation Forest score: {score:.2f}.",
        "decision": "Capacity exhaustion identified on {service}. HPA minimum may be set too low or maxReplicas preventing scale-out. Executing HPA scale-out configuration update.",
        "guardrail": "Guardrail triggered: {guardrail_reason}. Adjusting remediation plan to {new_action}.",
    },
    "cache_miss_spike": {
        "detection": "[{timestamp}] Anomaly confirmed on {service}. Cache miss rate elevated - Redis showing increased latency. Isolation Forest score: {score:.2f}.",
        "decision": "Cache degradation detected on {service}. Redis performance below baseline. Executing cache flush followed by scale-out if needed.",
        "guardrail": "Guardrail triggered: {guardrail_reason}. Adjusting remediation plan to {new_action}.",
    },
    "high_latency": {
        "detection": "[{timestamp}] Anomaly confirmed on {service}. p99 latency spiked {latency_delta:.0f}% over 3 consecutive windows. Isolation Forest score: {score:.2f}.",
        "decision": "Latency degradation identified on {service}. Error rates within normal bounds suggests resource contention rather than failure. Executing cache flush to reduce database load, followed by HPA scale-out.",
        "guardrail": "Guardrail triggered: {guardrail_reason}. Adjusting remediation plan to {new_action}.",
    },
}

# ── Templates for Phase 2 (Recovery Confirmation) ───────────────────────────

PHASE2_TEMPLATES: Dict[str, str] = {
    "pod_crash": "[{timestamp}] {service} recovery confirmed. Pods restarted and health checks passing. {metric_name} normalized to {metric_value}. Recovery completed in {recovery_time}s.",
    "oom_kill": "[{timestamp}] {service} scaled from {old_replicas} to {new_replicas} replicas. Memory pressure distributed across expanded pool. Recovery completed in {recovery_time}s.",
    "cpu_throttle": "[{timestamp}] {service} scaled from {old_replicas} to {new_replicas} replicas. CPU load normalized per instance. Recovery completed in {recovery_time}s.",
    "network_partition": "[{timestamp}] {service} connectivity restored. Network policy removed or pod restarted. Recovery completed in {recovery_time}s.",
    "replica_exhaustion": "[{timestamp}] {service} HPA reconfigured. Replicas scaling from {old_replicas} to {new_replicas}. Recovery completed in {recovery_time}s.",
    "cache_miss_spike": "[{timestamp}] {service} cache flushed - {keys_flushed} keys cleared. Cache miss rate normalized. Recovery completed in {recovery_time}s.",
    "high_latency": "[{timestamp}] {service} latency normalized to {metric_value} after {remediation_action}. Recovery completed in {recovery_time}s.",
}

# ── RCA Summary Templates ────────────────────────────────────────────────────

RCA_TEMPLATES: Dict[str, str] = {
    "independent_deviation": "Root cause localized to {service} via dependency correlation. Service shows deviation independently of callers ({callers}). Severity: {severity:.2f}.",
    "cascading_deviation": "Cascading failure detected via dependency walk. Fault originated in {origin} and propagated to {affected}. Call path: {path}.",
    "insufficient_signal": "Insufficient signal for upstream origin determination. Defaulting to reported service {service} with reduced confidence.",
}


class ReasoningEngine:
    """Generates human-readable reasoning for NovaSurge decisions."""

    def __init__(self, log_dir: str = "novasurge/data"):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.reasoning_log = self.log_dir / "reasoning_log.jsonl"
        self._buffer: List[Dict] = []

    def generate_phase1(
        self,
        anomaly_type: str,
        service: str,
        score: float,
        rca_result: Dict,
        decision: Dict,
        timestamp: Optional[str] = None,
    ) -> str:
        """Generate Phase 1 reasoning (detection + decision)."""
        if timestamp is None:
            timestamp = datetime.now(timezone.utc).strftime("%H:%M:%S")

        templates = PHASE1_TEMPLATES.get(anomaly_type, PHASE1_TEMPLATES["high_latency"])

        # Build detection message
        latency_delta = decision.get("latency_delta", 340)
        detection_msg = templates["detection"].format(
            timestamp=timestamp,
            service=service,
            score=score,
            latency_delta=latency_delta,
        )

        # Build decision message
        decision_msg = templates["decision"].format(
            service=service,
        )

        # Add RCA summary
        rca_summary = self._format_rca(rca_result, service)

        # Combine into full reasoning
        full_reasoning = f"{detection_msg}\n\n{rca_summary}\n\n{decision_msg}"

        # Log to file
        self._log_reasoning({
            "phase": 1,
            "timestamp": timestamp,
            "anomaly_type": anomaly_type,
            "service": service,
            "score": score,
            "reasoning": full_reasoning,
            "rca": rca_result,
            "decision": decision.get("primary_remediation"),
        })

        return full_reasoning

    def generate_phase2(
        self,
        anomaly_type: str,
        service: str,
        recovery_time: float,
        remediation_action: str,
        old_replicas: int = 2,
        new_replicas: int = 4,
        metric_name: str = "p99 latency",
        metric_value: str = "138ms",
        keys_flushed: int = 0,
        timestamp: Optional[str] = None,
    ) -> str:
        """Generate Phase 2 reasoning (recovery confirmation)."""
        if timestamp is None:
            timestamp = datetime.now(timezone.utc).strftime("%H:%M:%S")

        template = PHASE2_TEMPLATES.get(anomaly_type, PHASE2_TEMPLATES["high_latency"])

        reasoning = template.format(
            timestamp=timestamp,
            service=service,
            recovery_time=recovery_time,
            remediation_action=remediation_action,
            old_replicas=old_replicas,
            new_replicas=new_replicas,
            metric_name=metric_name,
            metric_value=metric_value,
            keys_flushed=keys_flushed,
        )

        self._log_reasoning({
            "phase": 2,
            "timestamp": timestamp,
            "anomaly_type": anomaly_type,
            "service": service,
            "recovery_time": recovery_time,
            "reasoning": reasoning,
        })

        return reasoning

    def _format_rca(self, rca_result: Dict, service: str) -> str:
        """Format RCA result into human-readable summary."""
        origin = rca_result.get("true_origin", service)
        confidence = rca_result.get("confidence", 0.7)
        call_path = rca_result.get("call_path", [service])
        reasoning = rca_result.get("reasoning", "")

        return f"RCA Analysis: {origin} identified as true origin (confidence: {confidence:.2f}). Path: {' -> '.join(call_path)}."

    def _log_reasoning(self, entry: Dict) -> None:
        """Append reasoning entry to JSONL file."""
        with open(self.reasoning_log, "a") as f:
            f.write(json.dumps(entry) + "\n")
        self._buffer.append(entry)

        # Keep buffer limited to last 100 entries
        if len(self._buffer) > 100:
            self._buffer.pop(0)

    def get_recent(self, n: int = 10) -> List[Dict]:
        """Get recent reasoning entries from buffer."""
        return self._buffer[-n:]

    def get_all_from_file(self) -> List[Dict]:
        """Read all reasoning entries from log file."""
        entries = []
        if self.reasoning_log.exists():
            with open(self.reasoning_log, "r") as f:
                for line in f:
                    if line.strip():
                        entries.append(json.loads(line))
        return entries


# ── Global instance ─────────────────────────────────────────────────────────

_engine: Optional[ReasoningEngine] = None


def get_engine() -> ReasoningEngine:
    """Get or create the global reasoning engine."""
    global _engine
    if _engine is None:
        _engine = ReasoningEngine()
    return _engine


def generate_phase1_reasoning(
    anomaly_type: str,
    service: str,
    score: float,
    rca_result: Dict,
    decision: Dict,
    timestamp: Optional[str] = None,
) -> str:
    """Convenience function for Phase 1 reasoning."""
    return get_engine().generate_phase1(
        anomaly_type, service, score, rca_result, decision, timestamp
    )


def generate_phase2_reasoning(
    anomaly_type: str,
    service: str,
    recovery_time: float,
    remediation_action: str,
    **kwargs,
) -> str:
    """Convenience function for Phase 2 reasoning."""
    return get_engine().generate_phase2(
        anomaly_type, service, recovery_time, remediation_action, **kwargs
    )


# ── Standalone test ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    # Test Phase 1
    test_anomaly = {
        "anomaly_type": "high_latency",
        "affected_service": "order-service",
        "score": -0.74,
        "latency_delta": 340,
    }
    test_rca = {
        "true_origin": "order-service",
        "confidence": 0.87,
        "call_path": ["api-gateway", "order-service"],
        "reasoning": "order-service deviates independently",
    }
    test_decision = {
        "primary_remediation": "cache_flush",
        "fallback_remediation": "hpa_scaleout",
        "latency_delta": 340,
    }

    print("=== Phase 1 Reasoning ===")
    phase1 = generate_phase1_reasoning(
        anomaly_type="high_latency",
        service="order-service",
        score=-0.74,
        rca_result=test_rca,
        decision=test_decision,
    )
    print(phase1)
    print()

    # Test Phase 2
    print("=== Phase 2 Reasoning ===")
    phase2 = generate_phase2_reasoning(
        anomaly_type="high_latency",
        service="order-service",
        recovery_time=8.0,
        remediation_action="cache_flush",
        metric_value="138ms",
    )
    print(phase2)
