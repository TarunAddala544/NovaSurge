"""
novasurge/chaos/injectors/network_partition.py

Chaos injector: create a deny-all NetworkPolicy for a service.
No ingress/egress rules = deny all traffic in and out.
"""

import logging
from datetime import datetime, timezone

from novasurge.k8s_client import get_clients, NAMESPACE

logger = logging.getLogger("novasurge.injectors.network_partition")


def _policy_name(service: str) -> str:
    return f"isolate-{service}"


def inject(service: str) -> dict:
    """
    Create a deny-all NetworkPolicy for `service`.

    Returns:
        {
          "success": bool,
          "injected_at": ISO8601,
          "target_pod": str (policy name),
          "details": {...}
        }
    """
    _, _, networking_v1, _ = get_clients()
    injected_at = datetime.now(timezone.utc).isoformat()
    policy_name = _policy_name(service)

    # Build deny-all NetworkPolicy body (no ingress/egress rules)
    policy_body = {
        "apiVersion": "networking.k8s.io/v1",
        "kind": "NetworkPolicy",
        "metadata": {
            "name": policy_name,
            "namespace": NAMESPACE,
        },
        "spec": {
            "podSelector": {
                "matchLabels": {"app": service}
            },
            "policyTypes": ["Ingress", "Egress"],
            # Intentionally empty — no rules means deny all
        },
    }

    logger.info(f"[network_partition] Creating deny-all NetworkPolicy={policy_name} for service={service}")
    print(f"  💥 [network_partition] Isolating {service}: creating NetworkPolicy/{policy_name}")

    try:
        networking_v1.create_namespaced_network_policy(
            namespace=NAMESPACE,
            body=policy_body,
        )
    except Exception as exc:
        # If policy already exists from a previous failed round, that's fine
        if "already exists" in str(exc).lower() or "conflict" in str(exc).lower():
            logger.warning(f"[network_partition] NetworkPolicy {policy_name} already exists — treating as injected")
        else:
            logger.error(f"[network_partition] Failed to create NetworkPolicy: {exc}")
            return {
                "success": False,
                "injected_at": injected_at,
                "target_pod": policy_name,
                "details": {"error": str(exc)},
            }

    logger.info(f"[network_partition] {service} is now fully isolated (deny all traffic)")

    return {
        "success": True,
        "injected_at": injected_at,
        "target_pod": policy_name,
        "details": {
            "service": service,
            "policy_name": policy_name,
            "namespace": NAMESPACE,
            "effect": "deny all ingress and egress",
        },
    }


def reverse(service: str) -> dict:
    """Delete the deny-all NetworkPolicy, restoring normal traffic."""
    _, _, networking_v1, _ = get_clients()
    policy_name = _policy_name(service)

    logger.info(f"[network_partition] Deleting NetworkPolicy={policy_name} for service={service}")
    print(f"  ✅ [network_partition] Restoring {service}: deleting NetworkPolicy/{policy_name}")

    try:
        networking_v1.delete_namespaced_network_policy(
            name=policy_name,
            namespace=NAMESPACE,
        )
    except Exception as exc:
        if "not found" in str(exc).lower():
            logger.warning(f"[network_partition] NetworkPolicy {policy_name} not found — already removed")
            return {"success": True, "details": {"note": "policy was already absent"}}
        logger.error(f"[network_partition] Failed to delete NetworkPolicy: {exc}")
        return {"success": False, "details": {"error": str(exc)}}

    return {"success": True, "details": {"service": service, "policy_deleted": policy_name}}


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    svc = sys.argv[1] if len(sys.argv) > 1 else "product-service"
    result = inject(svc)
    import json
    print(json.dumps(result, indent=2))
