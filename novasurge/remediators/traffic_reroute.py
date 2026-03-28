"""
novasurge/remediators/traffic_reroute.py

1. Read the Nginx ConfigMap from namespace shopfusion.
2. Update upstream server to the first healthy replica IP of the target service.
3. Apply patched ConfigMap.
4. exec `nginx -s reload` into the Nginx pod.
5. Confirm by hitting /health through Nginx on port 30080.
Returns: {success, completed_at, recovery_time_seconds, details}
"""

import asyncio
import re
import time
from datetime import datetime, timezone

import httpx

from novasurge.k8s_client import get_clients, NAMESPACE

NGINX_CONFIGMAP_NAME = "nginx-config"
NGINX_POD_LABEL = "app=nginx"
HEALTH_URL_TEMPLATE = "http://localhost:30080/{service_path}/health"
SERVICE_PATH_MAP = {
    "api-gateway": "",
    "product-service": "products",
    "order-service": "orders",
    "payment-service": "payments",
    "notification-service": "notifications",
}


def _get_healthy_replica_ip(core_v1, service: str) -> str | None:
    """Return the pod IP of the first Running pod for `service`."""
    pods = core_v1.list_namespaced_pod(
        namespace=NAMESPACE,
        label_selector=f"app={service}",
    )
    for pod in pods.items:
        if pod.status.phase == "Running" and pod.status.pod_ip:
            return pod.status.pod_ip
    return None


def _patch_upstream(nginx_conf: str, service: str, new_ip: str) -> str:
    """
    Replace the upstream block for `service` with the new IP.
    Looks for patterns like:
        upstream order-service { server <IP>:<PORT>; }
    Falls back to a simple IP replacement if the named upstream is not found.
    """
    # Try named upstream block first
    pattern = rf"(upstream\s+{re.escape(service)}\s*\{{[^}}]*server\s+)([^\s;]+)(.*?\}})"
    replacement = rf"\g<1>{new_ip}:8080\g<3>"
    patched, count = re.subn(pattern, replacement, nginx_conf, flags=re.DOTALL)
    if count:
        return patched

    # Fallback: replace any existing server directive referencing this service by name
    fallback_pattern = rf"(#\s*{re.escape(service)}[^\n]*\n\s*server\s+)([^\s;]+)"
    patched, count = re.subn(fallback_pattern, rf"\g<1>{new_ip}:8080", nginx_conf)
    if count:
        return patched

    # Last resort: append a server directive comment so the change is visible
    return nginx_conf + f"\n# rerouted {service} -> {new_ip}:8080\n"


async def remediate(service: str) -> dict:
    core_v1, apps_v1, _, _ = get_clients()
    start_ts = time.monotonic()

    # ── 1. Find a healthy replica IP ─────────────────────────────────────────
    replica_ip = _get_healthy_replica_ip(core_v1, service)
    if not replica_ip:
        return {
            "success": False,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "recovery_time_seconds": 0,
            "details": f"No healthy Running pod found for {service}",
        }
    print(f"[traffic_reroute] Healthy replica IP for {service}: {replica_ip}")

    # ── 2. Read Nginx ConfigMap ───────────────────────────────────────────────
    cm = core_v1.read_namespaced_config_map(name=NGINX_CONFIGMAP_NAME, namespace=NAMESPACE)
    original_conf = (cm.data or {}).get("nginx.conf", "")
    if not original_conf:
        # Try first available key as fallback
        original_conf = next(iter((cm.data or {}).values()), "")
    print(f"[traffic_reroute] Read ConfigMap '{NGINX_CONFIGMAP_NAME}' ({len(original_conf)} chars)")

    # ── 3. Patch upstream ────────────────────────────────────────────────────
    patched_conf = _patch_upstream(original_conf, service, replica_ip)
    patch_body = {"data": {"nginx.conf": patched_conf}}
    core_v1.patch_namespaced_config_map(
        name=NGINX_CONFIGMAP_NAME, namespace=NAMESPACE, body=patch_body
    )
    print(f"[traffic_reroute] ConfigMap patched with upstream {replica_ip}:8080")

    # ── 4. exec nginx -s reload ──────────────────────────────────────────────
    nginx_pods = core_v1.list_namespaced_pod(
        namespace=NAMESPACE, label_selector=NGINX_POD_LABEL
    )
    nginx_running = [p for p in nginx_pods.items if p.status.phase == "Running"]
    if not nginx_running:
        return {
            "success": False,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "recovery_time_seconds": round(time.monotonic() - start_ts, 2),
            "details": "No Running Nginx pod found to exec reload",
        }

    nginx_pod_name = nginx_running[0].metadata.name
    print(f"[traffic_reroute] Running 'nginx -s reload' in pod {nginx_pod_name}")
    core_v1.connect_get_namespaced_pod_exec(
        name=nginx_pod_name,
        namespace=NAMESPACE,
        command=["nginx", "-s", "reload"],
        container="nginx",
        stderr=True,
        stdin=False,
        stdout=True,
        tty=False,
    )

    # ── 5. Health check via Nginx ────────────────────────────────────────────
    await asyncio.sleep(2)  # allow reload to propagate
    service_path = SERVICE_PATH_MAP.get(service, service.replace("-service", "s"))
    health_url = f"http://localhost:30080/{service_path}/health" if service_path else "http://localhost:30080/health"
    print(f"[traffic_reroute] Health check: GET {health_url}")

    health_ok = False
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(health_url)
            health_ok = resp.status_code == 200
            print(f"[traffic_reroute] Health response: {resp.status_code}")
    except Exception as exc:
        print(f"[traffic_reroute] Health check failed: {exc}")

    recovery_time = time.monotonic() - start_ts
    return {
        "success": health_ok,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "recovery_time_seconds": round(recovery_time, 2),
        "details": {
            "service": service,
            "rerouted_to_ip": replica_ip,
            "nginx_pod": nginx_pod_name,
            "health_url": health_url,
            "health_ok": health_ok,
        },
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
