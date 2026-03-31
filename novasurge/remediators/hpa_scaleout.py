"""
novasurge/remediators/hpa_scaleout.py

Patches HPA to minReplicas=2 / maxReplicas=6, then polls until
desiredReplicas == readyReplicas (timeout 90s).
Returns: {success, completed_at, recovery_time_seconds, details}
"""

import asyncio
import time
from datetime import datetime, timezone

from novasurge.k8s_client import get_clients, NAMESPACE


async def remediate(service: str) -> dict:
    core_v1, apps_v1, _, autoscaling_v2 = get_clients()
    start_ts = time.monotonic()

    # ── Patch HPA ────────────────────────────────────────────────────────────
    patch = {
        "spec": {
            "minReplicas": 2,
            "maxReplicas": 6,
        }
    }
    print(f"[hpa_scaleout] Patching HPA for {service} → min=2 max=6")
    autoscaling_v2.patch_namespaced_horizontal_pod_autoscaler(
        name=f"{service}-hpa",
        namespace=NAMESPACE,
        body=patch,
    )

    # ── Poll until desiredReplicas == readyReplicas (timeout 90s) ────────────
    timeout = 90
    poll_interval = 3
    elapsed = 0
    desired = None
    ready = None

    while elapsed < timeout:
        await asyncio.sleep(poll_interval)
        elapsed += poll_interval
        hpa = autoscaling_v2.read_namespaced_horizontal_pod_autoscaler(
            name=f"{service}-hpa", namespace=NAMESPACE
        )
        desired = hpa.status.desired_replicas or 0
        ready = hpa.status.current_replicas or 0
        print(f"[hpa_scaleout] desired={desired} ready={ready} ({elapsed}s)")
        if desired > 0 and desired == ready:
            break

    recovery_time = time.monotonic() - start_ts
    success = desired is not None and desired == ready

    if success:
        print(f"[hpa_scaleout] Scale-out complete: {ready} replicas ready in {recovery_time:.1f}s")
    else:
        print(f"[hpa_scaleout] Timeout: desired={desired} ready={ready} after {timeout}s")

    return {
        "success": success,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "recovery_time_seconds": round(recovery_time, 2),
        "details": {
            "service": service,
            "desired_replicas": desired,
            "ready_replicas": ready,
            "hpa_patch": patch["spec"],
        },
    }


# ── Standalone test ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    import os
    os.environ.setdefault("NOVASURGE_MOCK_K8S", "true")

    async def main():
        result = await remediate("payment-service")
        import json
        print(json.dumps(result, indent=2))

    asyncio.run(main())
