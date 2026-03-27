"""
novasurge/remediators/pod_restart.py

Deletes the target pod and polls until a new pod is Running.
Returns: {success, completed_at, recovery_time_seconds, details}
"""

import asyncio
import time
from datetime import datetime, timezone

from novasurge.k8s_client import get_clients, NAMESPACE


async def remediate(service: str) -> dict:
    core_v1, apps_v1, _, _ = get_clients()
    start_ts = time.monotonic()
    started_at = datetime.now(timezone.utc).isoformat()

    # ── Find a Running pod for the service ──────────────────────────────────
    pods = core_v1.list_namespaced_pod(
        namespace=NAMESPACE,
        label_selector=f"app={service}",
    )
    running = [p for p in pods.items if p.status.phase == "Running"]
    if not running:
        return {
            "success": False,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "recovery_time_seconds": 0,
            "details": f"No Running pods found for {service}",
        }

    target_pod = running[0].metadata.name
    print(f"[pod_restart] Deleting pod {target_pod} for service {service}")

    # ── Delete the pod ───────────────────────────────────────────────────────
    core_v1.delete_namespaced_pod(
        name=target_pod,
        namespace=NAMESPACE,
        grace_period_seconds=0,
    )

    # ── Poll until a NEW Running pod exists (timeout 60s) ───────────────────
    timeout = 60
    poll_interval = 2
    elapsed = 0
    new_pod_name = None

    while elapsed < timeout:
        await asyncio.sleep(poll_interval)
        elapsed += poll_interval
        pods = core_v1.list_namespaced_pod(
            namespace=NAMESPACE,
            label_selector=f"app={service}",
        )
        for p in pods.items:
            if p.metadata.name != target_pod and p.status.phase == "Running":
                new_pod_name = p.metadata.name
                break
        if new_pod_name:
            break
        print(f"[pod_restart] Waiting for new pod… ({elapsed}s)")

    recovery_time = time.monotonic() - start_ts

    if new_pod_name:
        print(f"[pod_restart] New pod {new_pod_name} is Running after {recovery_time:.1f}s")
        return {
            "success": True,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "recovery_time_seconds": round(recovery_time, 2),
            "details": {
                "deleted_pod": target_pod,
                "new_pod": new_pod_name,
                "service": service,
            },
        }
    else:
        print(f"[pod_restart] Timeout waiting for new pod after {recovery_time:.1f}s")
        return {
            "success": False,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "recovery_time_seconds": round(recovery_time, 2),
            "details": f"Timeout: new Running pod for {service} did not appear within {timeout}s",
        }


# ── Standalone test ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    import os
    os.environ.setdefault("NOVASURGE_MOCK_K8S", "true")

    async def main():
        result = await remediate("order-service")
        import json
        print(json.dumps(result, indent=2))

    asyncio.run(main())
