"""
novasurge/chaos/injectors/replica_reduction.py

Chaos injector: patch HPA to minReplicas=1, maxReplicas=1.
Saves original HPA spec for reversal.
"""

import json
import os
import time
import logging
from datetime import datetime, timezone

from novasurge.k8s_client import get_clients, NAMESPACE

logger = logging.getLogger("novasurge.injectors.replica_reduction")

STATE_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "state")
os.makedirs(STATE_DIR, exist_ok=True)


def _state_path(service: str) -> str:
    return os.path.join(STATE_DIR, f"original_hpa_{service}.json")


def inject(service: str) -> dict:
    """
    Read current HPA spec, save it, then patch minReplicas=1, maxReplicas=1.
    Wait for scale-down to complete (only 1 pod running).

    Returns:
        {
          "success": bool,
          "injected_at": ISO8601,
          "target_pod": str (HPA name),
          "details": {...}
        }
    """
    core_v1, _, _, autoscaling_v2 = get_clients()
    injected_at = datetime.now(timezone.utc).isoformat()

    # Read current HPA
    logger.info(f"[replica_reduction] Reading HPA for service={service}")
    hpa = autoscaling_v2.read_namespaced_horizontal_pod_autoscaler(
        name=f"{service}-hpa",
        namespace=NAMESPACE,
    )

    original_spec = {
        "service": service,
        "min_replicas": hpa.spec.min_replicas,
        "max_replicas": hpa.spec.max_replicas,
    }
    state_path = _state_path(service)
    with open(state_path, "w") as f:
        json.dump(original_spec, f, indent=2)
    logger.info(f"[replica_reduction] Original HPA saved to {state_path}: {original_spec}")

    # Patch to min=1, max=1
    patch_body = {
        "spec": {
            "minReplicas": 1,
            "maxReplicas": 1,
        }
    }

    logger.info(f"[replica_reduction] Patching HPA={service} → minReplicas=1 maxReplicas=1")
    print(f"  💥 [replica_reduction] Reducing replicas of {service} to 1")
    autoscaling_v2.patch_namespaced_horizontal_pod_autoscaler(
        name=f"{service}-hpa",
        namespace=NAMESPACE,
        body=patch_body,
    )

    # Wait for scale-down: only 1 pod running
    _wait_for_scale_down(service, core_v1)

    return {
        "success": True,
        "injected_at": injected_at,
        "target_pod": service,
        "details": {
            "service": service,
            "original_min": original_spec["min_replicas"],
            "original_max": original_spec["max_replicas"],
            "patched_to": {"min": 1, "max": 1},
            "state_path": state_path,
        },
    }


def reverse(service: str) -> dict:
    """Restore original HPA spec from saved state."""
    state_path = _state_path(service)
    if not os.path.exists(state_path):
        msg = f"No saved HPA state at {state_path}"
        logger.error(f"[replica_reduction] {msg}")
        return {"success": False, "details": {"error": msg}}

    with open(state_path) as f:
        state = json.load(f)

    _, _, _, autoscaling_v2 = get_clients()

    patch_body = {
        "spec": {
            "minReplicas": state["min_replicas"],
            "maxReplicas": state["max_replicas"],
        }
    }

    logger.info(f"[replica_reduction] Restoring HPA={service} to min={state['min_replicas']} max={state['max_replicas']}")
    print(f"  ✅ [replica_reduction] Restoring {service} HPA to original spec")
    autoscaling_v2.patch_namespaced_horizontal_pod_autoscaler(
        name=f"{service}-hpa",
        namespace=NAMESPACE,
        body=patch_body,
    )

    os.remove(state_path)
    return {"success": True, "details": {"service": service, "restored": state}}


def _wait_for_scale_down(service: str, core_v1, timeout: int = 120) -> None:
    """Poll until exactly 1 pod is running for the service."""
    deadline = time.time() + timeout
    logger.info(f"[replica_reduction] Waiting for {service} to scale down to 1 pod...")
    while time.time() < deadline:
        pod_list = core_v1.list_namespaced_pod(
            namespace=NAMESPACE,
            label_selector=f"app={service}",
        )
        running = [p for p in pod_list.items if p.status.phase == "Running"]
        logger.debug(f"[replica_reduction] {service} running pods: {len(running)}")
        if len(running) == 1:
            logger.info(f"[replica_reduction] {service} scaled down to 1 pod: {running[0].metadata.name}")
            return
        time.sleep(5)
    logger.warning(f"[replica_reduction] Timed out waiting for {service} to scale down to 1 pod")


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    svc = sys.argv[1] if len(sys.argv) > 1 else "payment-service"
    result = inject(svc)
    import json
    print(json.dumps(result, indent=2))
