"""
novasurge/k8s_client.py

Shared Kubernetes client factory.
Set USE_MOCK=True for the first 6 hours before Person 1's cluster is ready.
Set USE_MOCK=False once kubeconfig at ~/.kube/config is confirmed live.
"""

import os
import json
import logging
from datetime import datetime, timezone

logger = logging.getLogger("novasurge.k8s_client")

# ─── Toggle here or via env var ───────────────────────────────────────────────
USE_MOCK: bool = os.environ.get("NOVASURGE_MOCK_K8S", "true").lower() == "true"
NAMESPACE: str = "shopfusion"


# ─── Real client ──────────────────────────────────────────────────────────────

def get_real_clients():
    """Return (CoreV1Api, AppsV1Api, NetworkingV1Api, AutoscalingV2Api)."""
    from kubernetes import client, config
    config.load_kube_config()
    return (
        client.CoreV1Api(),
        client.AppsV1Api(),
        client.NetworkingV1Api(),
        client.AutoscalingV2Api(),
    )


# ─── Mock client ──────────────────────────────────────────────────────────────

class _MockResponse:
    """Mimics just enough of the k8s response surface for injectors/remediators."""

    def __init__(self, data=None):
        self._data = data or {}

    def to_dict(self):
        return self._data


class MockK8sClient:
    """
    Prints every K8s operation instead of executing it.
    Returns plausible mock data so callers can continue without branching.
    """

    NS = NAMESPACE

    def __init__(self):
        # Bug 2 fix: track replica counts per service so replica_reduction
        # can scale down and _wait_for_scale_down exits cleanly.
        self._mock_replica_counts: dict = {}

    # ── Core V1 ───────────────────────────────────────────────────────────────

    def list_namespaced_pod(self, namespace, label_selector=None, **kwargs):
        tag = f"[MOCK] list_namespaced_pod ns={namespace} selector={label_selector}"
        logger.info(tag)
        print(tag)

        svc = (label_selector or "app=unknown").split("=")[-1]

        # Bug 2 fix: honour the replica count that was set by patch_hpa.
        # Default is 2 so everything that doesn't call patch_hpa still works.
        count = self._mock_replica_counts.get(svc, 2)

        pods = []
        for i in range(count):
            pods.append(type("Pod", (), {
                "metadata": type("Meta", (), {
                    "name": f"{svc}-deploy-mock{i}-abcde",
                    "namespace": namespace,
                    "labels": {"app": svc},
                })(),
                "status": type("Status", (), {
                    "phase": "Running",
                    "pod_ip": f"10.0.{i}.{10 + i}",
                    "conditions": [
                        type("Cond", (), {"type": "Ready", "status": "True"})()
                    ],
                })(),
                "spec": type("Spec", (), {"node_name": f"node-{i}"})(),
            })())
        return type("PodList", (), {"items": pods})()

    def delete_namespaced_pod(self, name, namespace, body=None, **kwargs):
        tag = f"[MOCK] delete_namespaced_pod name={name} ns={namespace}"
        logger.info(tag)
        print(tag)
        return _MockResponse({"status": "deleted", "name": name})

    def read_namespaced_config_map(self, name, namespace, **kwargs):
        tag = f"[MOCK] read_namespaced_config_map name={name} ns={namespace}"
        logger.info(tag)
        print(tag)
        return type("CM", (), {
            "metadata": type("Meta", (), {"name": name, "namespace": namespace})(),
            "data": {"nginx.conf": "upstream backend { server 10.0.0.1:8080; }"},
        })()

    def patch_namespaced_config_map(self, name, namespace, body, **kwargs):
        tag = f"[MOCK] patch_namespaced_config_map name={name} ns={namespace}"
        logger.info(tag)
        print(tag)
        return _MockResponse()

    def create_namespaced_network_policy(self, namespace, body, **kwargs):
        tag = f"[MOCK] create_namespaced_network_policy ns={namespace} name={body['metadata']['name']}"
        logger.info(tag)
        print(tag)
        return _MockResponse()

    def delete_namespaced_network_policy(self, name, namespace, **kwargs):
        tag = f"[MOCK] delete_namespaced_network_policy name={name} ns={namespace}"
        logger.info(tag)
        print(tag)
        return _MockResponse()

    # ── Apps V1 ───────────────────────────────────────────────────────────────

    def read_namespaced_deployment(self, name, namespace, **kwargs):
        tag = f"[MOCK] read_namespaced_deployment name={name} ns={namespace}"
        logger.info(tag)
        print(tag)
        return type("Deploy", (), {
            "metadata": type("Meta", (), {"name": name, "namespace": namespace})(),
            "spec": type("Spec", (), {
                "replicas": 2,
                "template": type("Tmpl", (), {
                    "spec": type("TSpec", (), {
                        "containers": [
                            type("Container", (), {
                                "name": name,
                                "resources": type("Res", (), {
                                    "limits": {"cpu": "500m", "memory": "512Mi"},
                                    "requests": {"cpu": "100m", "memory": "128Mi"},
                                })(),
                            })()
                        ]
                    })()
                })(),
            })(),
        })()

    def patch_namespaced_deployment(self, name, namespace, body, **kwargs):
        tag = f"[MOCK] patch_namespaced_deployment name={name} ns={namespace} body_keys={list(body.keys())}"
        logger.info(tag)
        print(tag)
        return _MockResponse()

    # ── Autoscaling V2 ────────────────────────────────────────────────────────

    def read_namespaced_horizontal_pod_autoscaler(self, name, namespace, **kwargs):
        tag = f"[MOCK] read_hpa name={name} ns={namespace}"
        logger.info(tag)
        print(tag)
        return type("HPA", (), {
            "metadata": type("Meta", (), {"name": name, "namespace": namespace})(),
            "spec": type("Spec", (), {"min_replicas": 2, "max_replicas": 5})(),
            "status": type("Status", (), {
                "desired_replicas": 2,
                "current_replicas": 2,
            })(),
        })()

    def patch_namespaced_horizontal_pod_autoscaler(self, name, namespace, body, **kwargs):
        tag = f"[MOCK] patch_hpa name={name} ns={namespace}"
        logger.info(tag)
        print(tag)

        # Bug 2 fix: record the new minReplicas so list_namespaced_pod returns
        # the correct count and _wait_for_scale_down exits without looping forever.
        spec = body.get("spec", {})
        if "minReplicas" in spec:
            self._mock_replica_counts[name] = spec["minReplicas"]
            logger.info(f"[MOCK] Recorded replica count for {name} = {spec['minReplicas']}")

        return _MockResponse()

    # ── stream exec (used by latency_injection) ───────────────────────────────

    def connect_get_namespaced_pod_exec(self, *args, **kwargs):
        command = kwargs.get("command", [])
        tag = f"[MOCK] pod_exec command={command}"
        logger.info(tag)
        print(tag)

        # Bug 1 fix: return a path-like string for `which` commands so
        # _ensure_tc sees "/usr/sbin/tc" and doesn't crash trying to install.
        if command and command[0] == "which":
            binary = command[1] if len(command) > 1 else "unknown"
            return f"/usr/sbin/{binary}"

        return "mock exec output"


# ─── Factory ──────────────────────────────────────────────────────────────────

def get_clients():
    """
    Returns (core_v1, apps_v1, networking_v1, autoscaling_v2).
    All four are the same MockK8sClient instance when USE_MOCK=True so that
    stateful mock behaviour (e.g. replica counts) is shared across callers.
    """
    if USE_MOCK:
        logger.warning("Using MockK8sClient — set NOVASURGE_MOCK_K8S=false when cluster is ready.")
        mock = MockK8sClient()
        return mock, mock, mock, mock
    return get_real_clients()
