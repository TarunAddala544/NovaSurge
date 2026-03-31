"""
novasurge/remediators/__init__.py

Exports the REGISTRY dict used by the orchestrator.
Each value is the async `remediate(service)` coroutine from its module.
"""

from novasurge.remediators.pod_restart     import remediate as pod_restart
from novasurge.remediators.hpa_scaleout    import remediate as hpa_scaleout
from novasurge.remediators.traffic_reroute import remediate as traffic_reroute
from novasurge.remediators.cache_flush     import remediate as cache_flush

REGISTRY = {
    "pod_restart":     pod_restart,
    "hpa_scaleout":    hpa_scaleout,
    "traffic_reroute": traffic_reroute,
    "cache_flush":     cache_flush,
}