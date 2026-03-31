"""
novasurge/chaos/injectors/cpu_throttle.py

Chaos injector: patch deployment resource limits to cpu=50m, memory=64Mi.
Stores original limits for reversal.
"""

import json
import os
import time
import logging
from datetime import datetime, timezone

from novasurge.k8s_client import get_clients, NAMESPACE

logger = logging.getLogger("novasurge.injectors.cpu_throttle")

STATE_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "state")
os.makedirs(STATE_DIR, exist_ok=True)

THROTTLED_CPU = "50m"
THROTTLED_MEM = "64Mi"


def _state_path(service: str) -> str:
    return os.path.join(STATE_DIR, f"original_limits_{service}.json")


def inject(service: str) -> dict:
    """
    Read current resource limits, save them, then patch to throttled values.
    Triggers pod restart with new limits.

    Returns:
        {
          "success": bool,
          "injected_at": ISO8601,
          "target_pod": str (deployment name),
          "details": {...}
        }
    """
    _, apps_v1, _, _ = get_clients()
    injected_at = datetime.now(timezone.utc).isoformat()

    # Read current deployment spec
    logger.info(f"[cpu_throttle] Reading deployment={service}")
    deploy = apps_v1.read_namespaced_deployment(name=service, namespace=NAMESPACE)

    containers = deploy.spec.template.spec.containers
    original_limits_list = []
    for c in containers:
        res = c.resources
        original_limits_list.append({
            "name": c.name,
            "limits": {
                "cpu": res.limits.get("cpu") if res.limits else None,
                "memory": res.limits.get("memory") if res.limits else None,
            },
            "requests": {
                "cpu": res.requests.get("cpu") if res.requests else None,
                "memory": res.requests.get("memory") if res.requests else None,
            },
        })

    # Persist original state
    state_path = _state_path(service)
    with open(state_path, "w") as f:
        json.dump({"service": service, "containers": original_limits_list}, f, indent=2)
    logger.info(f"[cpu_throttle] Original limits saved to {state_path}")

    # Build patch
    patch_containers = []
    for c in containers:
        patch_containers.append({
            "name": c.name,
            "resources": {
                "limits": {"cpu": THROTTLED_CPU, "memory": THROTTLED_MEM},
                "requests": {"cpu": "10m", "memory": "32Mi"},
            },
        })

    patch_body = {
        "spec": {
            "template": {
                "spec": {
                    "containers": patch_containers
                }
            }
        }
    }

    logger.info(f"[cpu_throttle] Patching deployment={service} → cpu={THROTTLED_CPU} mem={THROTTLED_MEM}")
    print(f"  💥 [cpu_throttle] Throttling {service}: cpu={THROTTLED_CPU} memory={THROTTLED_MEM}")
    apps_v1.patch_namespaced_deployment(name=service, namespace=NAMESPACE, body=patch_body)

    # Wait for pod restart with new limits
    _wait_for_running(service)

    return {
        "success": True,
        "injected_at": injected_at,
        "target_pod": service,
        "details": {
            "service": service,
            "throttled_to": {"cpu": THROTTLED_CPU, "memory": THROTTLED_MEM},
            "original_state_path": state_path,
        },
    }


def reverse(service: str) -> dict:
    """Restore original resource limits from saved state."""
    state_path = _state_path(service)
    if not os.path.exists(state_path):
        msg = f"No saved state at {state_path} — cannot reverse cpu_throttle for {service}"
        logger.error(f"[cpu_throttle] {msg}")
        return {"success": False, "details": {"error": msg}}

    with open(state_path) as f:
        state = json.load(f)

    _, apps_v1, _, _ = get_clients()

    patch_containers = []
    for c in state["containers"]:
        patch_containers.append({
            "name": c["name"],
            "resources": {
                "limits": c["limits"],
                "requests": c["requests"],
            },
        })

    patch_body = {
        "spec": {
            "template": {
                "spec": {"containers": patch_containers}
            }
        }
    }

    logger.info(f"[cpu_throttle] Reversing throttle on deployment={service}")
    print(f"  ✅ [cpu_throttle] Restoring {service} to original limits")
    apps_v1.patch_namespaced_deployment(name=service, namespace=NAMESPACE, body=patch_body)

    _wait_for_running(service)
    os.remove(state_path)

    return {"success": True, "details": {"service": service, "restored": state["containers"]}}


def _wait_for_running(service: str, timeout: int = 60) -> None:
    """Poll until at least one pod for the deployment is Running."""
    core_v1, _, _, _ = get_clients()
    deadline = time.time() + timeout
    logger.info(f"[cpu_throttle] Waiting for {service} pod to reach Running...")
    while time.time() < deadline:
        pod_list = core_v1.list_namespaced_pod(
            namespace=NAMESPACE,
            label_selector=f"app={service}",
        )
        running = [p for p in pod_list.items if p.status.phase == "Running"]
        if running:
            logger.info(f"[cpu_throttle] {service} pod is Running: {running[0].metadata.name}")
            return
        time.sleep(3)
    logger.warning(f"[cpu_throttle] Timed out waiting for {service} to reach Running state")


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    svc = sys.argv[1] if len(sys.argv) > 1 else "payment-service"
    result = inject(svc)
    import json
    print(json.dumps(result, indent=2))
