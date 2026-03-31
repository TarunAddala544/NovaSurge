"""
novasurge/chaos/injectors/latency_injection.py

Chaos injector: inject 500ms ± 100ms latency via tc netem inside the pod.
Uses kubernetes.stream to exec into the pod.
Installs iproute2 if tc is not found.
"""

import logging
from datetime import datetime, timezone

from novasurge.k8s_client import get_clients, USE_MOCK, NAMESPACE

logger = logging.getLogger("novasurge.injectors.latency_injection")


def _get_pod_name(service: str, core_v1) -> str:
    pod_list = core_v1.list_namespaced_pod(
        namespace=NAMESPACE,
        label_selector=f"app={service}",
    )
    running = [p for p in pod_list.items if p.status.phase == "Running"]
    if not running:
        raise RuntimeError(f"No Running pods found for service={service}")
    return running[0].metadata.name


def _exec_in_pod(core_v1, pod_name: str, command: list) -> str:
    """Execute a command in a pod and return stdout."""
    if USE_MOCK:
        # MockK8sClient prints the operation
        return core_v1.connect_get_namespaced_pod_exec(
            pod_name,
            NAMESPACE,
            command=command,
        )

    from kubernetes import stream
    return stream.stream(
        core_v1.connect_get_namespaced_pod_exec,
        pod_name,
        NAMESPACE,
        command=command,
        stderr=True,
        stdin=False,
        stdout=True,
        tty=False,
    )


def _ensure_tc(core_v1, pod_name: str) -> None:
    """Check if tc exists; if not, install iproute2 then verify."""
    logger.info(f"[latency_injection] Checking if tc is available in pod={pod_name}")
    result = _exec_in_pod(core_v1, pod_name, ["which", "tc"])
    if result and "/tc" in str(result):
        logger.info("[latency_injection] tc is available")
        return

    logger.warning("[latency_injection] tc not found — installing iproute2...")
    print(f"  ⚙️  [latency_injection] Installing iproute2 in pod={pod_name}...")
    install_result = _exec_in_pod(
        core_v1, pod_name,
        ["apt-get", "install", "-y", "iproute2"],
    )
    logger.info(f"[latency_injection] iproute2 install output: {install_result}")

    # Verify again
    verify = _exec_in_pod(core_v1, pod_name, ["which", "tc"])
    if not verify or "/tc" not in str(verify):
        return {"success": False, "skipped": True, "reason": "tc not available in pod, skipping latency injection"}
    logger.info("[latency_injection] tc now available after install")


def inject(service: str) -> dict:
    """
    Inject 500ms ± 100ms latency on eth0 of the target pod using tc netem.

    Returns:
        {
          "success": bool,
          "injected_at": ISO8601,
          "target_pod": str,
          "details": {...}
        }
    """
    core_v1, _, _, _ = get_clients()
    injected_at = datetime.now(timezone.utc).isoformat()

    pod_name = _get_pod_name(service, core_v1)
    logger.info(f"[latency_injection] Target pod={pod_name} for service={service}")
    print(f"  💥 [latency_injection] Injecting latency into {service} pod={pod_name}")

    _ensure_tc(core_v1, pod_name)

    tc_command = [
        "tc", "qdisc", "add", "dev", "eth0", "root",
        "netem", "delay", "500ms", "100ms", "distribution", "normal",
    ]

    try:
        result = _exec_in_pod(core_v1, pod_name, tc_command)
        logger.info(f"[latency_injection] tc output: {result}")
    except Exception as exc:
        logger.error(f"[latency_injection] exec failed: {exc}")
        raise

    logger.info(f"[latency_injection] Latency injected: 500ms ±100ms normal distribution on eth0")

    return {
        "success": True,
        "injected_at": injected_at,
        "target_pod": pod_name,
        "details": {
            "service": service,
            "delay": "500ms",
            "jitter": "100ms",
            "distribution": "normal",
            "interface": "eth0",
            "tc_command": " ".join(tc_command),
        },
    }


def reverse(service: str) -> dict:
    """Remove the netem qdisc from eth0."""
    core_v1, _, _, _ = get_clients()

    pod_name = _get_pod_name(service, core_v1)
    logger.info(f"[latency_injection] Reversing latency on pod={pod_name}")
    print(f"  ✅ [latency_injection] Removing latency from {service} pod={pod_name}")

    tc_del_command = ["tc", "qdisc", "del", "dev", "eth0", "root"]

    try:
        result = _exec_in_pod(core_v1, pod_name, tc_del_command)
        logger.info(f"[latency_injection] tc del output: {result}")
    except Exception as exc:
        logger.error(f"[latency_injection] reverse exec failed: {exc}")
        return {"success": False, "details": {"error": str(exc), "pod": pod_name}}

    return {"success": True, "details": {"service": service, "pod": pod_name, "latency": "removed"}}


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    svc = sys.argv[1] if len(sys.argv) > 1 else "order-service"
    result = inject(svc)
    import json
    print(json.dumps(result, indent=2))
