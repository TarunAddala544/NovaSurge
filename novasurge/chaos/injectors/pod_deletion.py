"""
novasurge/chaos/injectors/pod_deletion.py

Chaos injector: delete a random pod from a deployment.
K8s reschedules automatically — we do NOT manually reschedule.
"""

import random
import logging
from datetime import datetime, timezone

from novasurge.k8s_client import get_clients, USE_MOCK, NAMESPACE

logger = logging.getLogger("novasurge.injectors.pod_deletion")


def inject(service: str) -> dict:
    """
    List all pods for `service`, pick one at random, delete it.

    Returns:
        {
          "success": bool,
          "injected_at": ISO8601,
          "target_pod": str,
          "details": {...}
        }
    """
    core_v1, _, _, _ = get_clients()

    label_selector = f"app={service}"
    logger.info(f"[pod_deletion] Listing pods for service={service} selector={label_selector}")

    pod_list = core_v1.list_namespaced_pod(
        namespace=NAMESPACE,
        label_selector=label_selector,
    )

    running_pods = [
        p for p in pod_list.items
        if p.status.phase == "Running"
    ]

    if not running_pods:
        msg = f"No Running pods found for service={service}"
        logger.error(f"[pod_deletion] {msg}")
        return {
            "success": False,
            "injected_at": datetime.now(timezone.utc).isoformat(),
            "target_pod": None,
            "details": {"error": msg},
        }

    target_pod = random.choice(running_pods)
    pod_name = target_pod.metadata.name
    injected_at = datetime.now(timezone.utc).isoformat()

    logger.info(f"[pod_deletion] Deleting pod={pod_name} from service={service}")
    print(f"  💥 [pod_deletion] Deleting pod: {pod_name}")

    if USE_MOCK:
        delete_opts = None
    else:
        from kubernetes import client as k8s_client
        delete_opts = k8s_client.V1DeleteOptions(grace_period_seconds=0)

    core_v1.delete_namespaced_pod(
        name=pod_name,
        namespace=NAMESPACE,
        body=delete_opts,
    )

    logger.info(f"[pod_deletion] Pod {pod_name} deleted. K8s will reschedule automatically.")

    return {
        "success": True,
        "injected_at": injected_at,
        "target_pod": pod_name,
        "details": {
            "service": service,
            "namespace": NAMESPACE,
            "pod_ip": target_pod.status.pod_ip,
            "note": "K8s will reschedule automatically",
        },
    }


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    svc = sys.argv[1] if len(sys.argv) > 1 else "order-service"
    result = inject(svc)
    import json
    print(json.dumps(result, indent=2))
