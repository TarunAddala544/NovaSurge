import json
import os
from datetime import datetime

# Ensure data directory exists
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
LOG_FILE = os.path.join(DATA_DIR, "reasoning_log.jsonl")

os.makedirs(DATA_DIR, exist_ok=True)


# ==============================
# DETECTION TEMPLATES
# ==============================

def pod_crash(p):
    return (
        f"Anomaly confirmed on {p['service']}. Active connections dropped "
        f"to zero and error rate spiked {p['error_delta']:.0f}x above baseline. "
        f"Isolation Forest score: {p['iforest_score']:.2f}. Pattern matches "
        f"pod termination. Root cause: {p['rca_origin']}. Executing {p['remediation']} "
        f"— fastest recovery path for hard crashes. Priority: {p['priority']}/10."
    )


def cpu_throttle(p):
    return (
        f"CPU exhaustion detected on {p['service']}. CPU utilization at "
        f"{p['cpu_pct']:.0f}% while request rate held at {p['request_rate']:.1f} req/s. "
        f"Isolation Forest score: {p['iforest_score']:.2f}. Resource starvation detected. "
        f"Root cause: {p['rca_origin']}. Executing {p['remediation']}."
    )


def network_partition(p):
    return (
        f"Network partition detected on {p['service']}. Request rate collapsed "
        f"{p['request_delta']:.0f}x and connections dropped to zero. "
        f"No CPU/memory anomaly. Isolation Forest score: {p['iforest_score']:.2f}. "
        f"Executing {p['remediation']} to restore connectivity."
    )


def high_latency(p):
    return (
        f"Latency degradation confirmed on {p['service']}. p99 latency "
        f"{p['p99_ms']:.0f}ms — {p['latency_delta']:.1f}x above baseline. "
        f"Isolation Forest score: {p['iforest_score']:.2f}. "
        f"LSTM predicted degradation {p['lstm_lead']:.0f}s early. "
        f"Executing {p['remediation']}."
    )


def replica_exhaustion(p):
    return (
        f"Capacity exhaustion on {p['service']}. Request rate {p['request_rate']:.1f} req/s "
        f"with insufficient replicas. Isolation Forest score: {p['iforest_score']:.2f}. "
        f"Executing {p['remediation']} to scale system."
    )


def cache_miss_spike(p):
    return (
        f"Cache miss storm on {p['service']}. Elevated request rate {p['request_rate']:.1f} req/s "
        f"causing DB latency spike {p['latency_delta']:.1f}x. "
        f"Isolation Forest score: {p['iforest_score']:.2f}. "
        f"Executing {p['remediation']} and warming cache."
    )


# ==============================
# RECOVERY TEMPLATES
# ==============================

def pod_restart(p):
    return (
        f"{p['service']} pod restarted successfully. Recovery in "
        f"{p['recovery_time']:.0f}s. Error rate normalized to "
        f"{p['current_error_rate']:.3f}."
    )


def hpa_scaleout(p):
    return (
        f"{p['service']} scaled from {p['old_replicas']} to {p['new_replicas']} replicas. "
        f"Load stabilized. Recovery completed in {p['recovery_time']:.0f}s."
    )


def traffic_reroute(p):
    return (
        f"Traffic rerouted away from {p['service']}. Nginx reloaded in "
        f"{p['nginx_reload_ms']:.0f}ms. Recovery completed in {p['recovery_time']:.0f}s."
    )


def cache_flush(p):
    return (
        f"Redis cache flushed for {p['service']}. Cleared {p['keys_flushed']} keys. "
        f"Latency normalized. Recovery completed in {p['recovery_time']:.0f}s."
    )


# ==============================
# GUARDRAIL TEMPLATE
# ==============================

def guardrail(p):
    return (
        f"Safety guardrail triggered: {p['reason']}. Switching from "
        f"{p['blocked_action']} to {p['fallback_action']} for {p['service']}."
    )


# ==============================
# TEMPLATE MAPPING
# ==============================

TEMPLATE_MAP = {
    "pod_crash_detected": pod_crash,
    "cpu_throttle_detected": cpu_throttle,
    "network_partition_detected": network_partition,
    "high_latency_detected": high_latency,
    "replica_exhaustion_detected": replica_exhaustion,
    "cache_miss_spike_detected": cache_miss_spike,

    "pod_restart_recovered": pod_restart,
    "hpa_scaleout_recovered": hpa_scaleout,
    "traffic_reroute_recovered": traffic_reroute,
    "cache_flush_recovered": cache_flush,

    "guardrail_triggered": guardrail
}


# ==============================
# MAIN FUNCTION
# ==============================

def generate(event_type, phase, params):
    key = f"{event_type}_{phase}"

    if key not in TEMPLATE_MAP:
        text = f"Unknown event: {key}"
    else:
        try:
            text = TEMPLATE_MAP[key](params)
        except KeyError as e:
            text = f"Template error: missing {str(e)}"

    log_entry = {
        "timestamp": datetime.now().isoformat(),
        "event_type": event_type,
        "phase": phase,
        "service": params.get("service"),
        "text": text
    }

    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(log_entry) + "\n")

    return text


# ==============================
# TEST RUN
# ==============================

if __name__ == "__main__":
    print(generate(
        "high_latency",
        "detected",
        {
            "service": "order-service",
            "p99_ms": 1200,
            "latency_delta": 3.4,
            "iforest_score": -0.71,
            "lstm_lead": 12,
            "remediation": "HPA scale-out"
        }
    ))