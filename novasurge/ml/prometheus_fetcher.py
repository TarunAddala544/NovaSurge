#!/usr/bin/env python3
"""
NovaSurge - Prometheus Metrics Fetcher
Fetches metrics from Prometheus for real-time inference.
"""

import httpx
import json
import os
from datetime import datetime
from typing import Dict, Optional

# Services to monitor
SERVICES = [
    "api-gateway",
    "product-service",
    "order-service",
    "payment-service",
    "notification-service",
]

# Default Prometheus URL
PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "http://localhost:9090")

# Cache for last known values
_last_metrics = {}


async def query_prometheus(promql: str) -> Optional[float]:
    """Query Prometheus with a PromQL expression."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(
                f"{PROMETHEUS_URL}/api/v1/query",
                params={"query": promql},
            )
            response.raise_for_status()
            data = response.json()

            if data.get("status") == "success" and data.get("data", {}).get("result"):
                result = data["data"]["result"][0]
                value = float(result["value"][1])
                return value
    except Exception as e:
        pass

    return None


def query_prometheus_sync(promql: str) -> Optional[float]:
    """Synchronous version of Prometheus query."""
    try:
        import requests

        response = requests.get(
            f"{PROMETHEUS_URL}/api/v1/query",
            params={"query": promql},
            timeout=5.0,
        )
        response.raise_for_status()
        data = response.json()

        if data.get("status") == "success" and data.get("data", {}).get("result"):
            result = data["data"]["result"][0]
            value = float(result["value"][1])
            return value
    except Exception as e:
        pass

    return None


def fetch_metrics_snapshot_sync() -> Dict[str, Dict[str, float]]:
    """
    Fetch current metrics snapshot for all services (synchronous).
    Returns metrics in the format expected by the API.
    """
    global _last_metrics

    metrics = {}
    any_success = False

    for service in SERVICES:
        service_metrics = {}

        # http_request_rate
        promql = f'rate(http_requests_total{{service="{service}"}}[1m])'
        value = query_prometheus_sync(promql)
        if value is not None:
            service_metrics["http_request_rate"] = value
            any_success = True
        else:
            # Use last known or synthetic default
            service_metrics["http_request_rate"] = _last_metrics.get(service, {}).get(
                "http_request_rate", get_default_for_service(service, "http_request_rate")
            )

        # error_rate
        promql = f'rate(http_requests_total{{service="{service}",status_code=~"5.."}}[1m])'
        value = query_prometheus_sync(promql)
        if value is not None:
            service_metrics["error_rate"] = value
            any_success = True
        else:
            service_metrics["error_rate"] = _last_metrics.get(service, {}).get(
                "error_rate", get_default_for_service(service, "error_rate")
            )

        # p99_latency (in ms)
        promql = f'histogram_quantile(0.99, rate(http_request_duration_seconds_bucket{{service="{service}"}}[1m])) * 1000'
        value = query_prometheus_sync(promql)
        if value is not None:
            service_metrics["p99_latency"] = value
            any_success = True
        else:
            service_metrics["p99_latency"] = _last_metrics.get(service, {}).get(
                "p99_latency", get_default_for_service(service, "p99_latency")
            )

        # cpu_usage
        promql = f'rate(container_cpu_usage_seconds_total{{pod=~"{service}.*"}}[1m])'
        value = query_prometheus_sync(promql)
        if value is not None:
            service_metrics["cpu_usage"] = value
            any_success = True
        else:
            service_metrics["cpu_usage"] = _last_metrics.get(service, {}).get(
                "cpu_usage", get_default_for_service(service, "cpu_usage")
            )

        # memory_usage (in MB)
        promql = f'container_memory_working_set_bytes{{pod=~"{service}.*"}} / 1024 / 1024'
        value = query_prometheus_sync(promql)
        if value is not None:
            service_metrics["memory_usage"] = value
            any_success = True
        else:
            service_metrics["memory_usage"] = _last_metrics.get(service, {}).get(
                "memory_usage", get_default_for_service(service, "memory_usage")
            )

        # active_connections
        promql = f'active_connections{{service="{service}"}}'
        value = query_prometheus_sync(promql)
        if value is not None:
            service_metrics["active_connections"] = value
            any_success = True
        else:
            service_metrics["active_connections"] = _last_metrics.get(service, {}).get(
                "active_connections", get_default_for_service(service, "active_connections")
            )

        metrics[service] = service_metrics

    # Update cache if any success
    if any_success:
        _last_metrics = metrics.copy()

    # Add staleness flag
    metrics["_staleness_warning"] = not any_success

    return metrics


def get_default_for_service(service: str, metric: str) -> float:
    """Get default value for a service/metric when Prometheus is unavailable."""
    defaults = {
        "api-gateway": {
            "http_request_rate": 50.0,
            "error_rate": 0.005,
            "p99_latency": 100.0,
            "cpu_usage": 0.2,
            "memory_usage": 150.0,
            "active_connections": 30.0,
        },
        "product-service": {
            "http_request_rate": 35.0,
            "error_rate": 0.003,
            "p99_latency": 55.0,
            "cpu_usage": 0.12,
            "memory_usage": 200.0,
            "active_connections": 20.0,
        },
        "order-service": {
            "http_request_rate": 15.0,
            "error_rate": 0.012,
            "p99_latency": 200.0,
            "cpu_usage": 0.22,
            "memory_usage": 170.0,
            "active_connections": 10.0,
        },
        "payment-service": {
            "http_request_rate": 11.5,
            "error_rate": 0.025,
            "p99_latency": 275.0,
            "cpu_usage": 0.2,
            "memory_usage": 140.0,
            "active_connections": 6.5,
        },
        "notification-service": {
            "http_request_rate": 7.5,
            "error_rate": 0.002,
            "p99_latency": 35.0,
            "cpu_usage": 0.06,
            "memory_usage": 100.0,
            "active_connections": 3.5,
        },
    }
    return defaults.get(service, {}).get(metric, 0.0)


def generate_synthetic_metrics() -> Dict[str, Dict[str, float]]:
    """Generate synthetic metrics when Prometheus is unavailable."""
    import random

    metrics = {}
    for service in SERVICES:
        base = get_default_for_service(service, "http_request_rate")
        metrics[service] = {
            "http_request_rate": base + random.gauss(0, base * 0.05),
            "error_rate": get_default_for_service(service, "error_rate") * (1 + random.gauss(0, 0.1)),
            "p99_latency": get_default_for_service(service, "p99_latency") * (1 + random.gauss(0, 0.05)),
            "cpu_usage": get_default_for_service(service, "cpu_usage") * (1 + random.gauss(0, 0.1)),
            "memory_usage": get_default_for_service(service, "memory_usage") * (1 + random.gauss(0, 0.05)),
            "active_connections": get_default_for_service(service, "active_connections") * (1 + random.gauss(0, 0.1)),
        }
    return metrics


if __name__ == "__main__":
    # Test the fetcher
    print("Testing Prometheus fetcher...")
    metrics = fetch_metrics_snapshot_sync()

    print("\nFetched metrics:")
    for service, service_metrics in metrics.items():
        if not service.startswith("_"):
            print(f"\n{service}:")
            for key, value in service_metrics.items():
                print(f"  {key}: {value:.4f}")

    if metrics.get("_staleness_warning"):
        print("\n⚠️  Prometheus unavailable - using synthetic/fallback data")
    else:
        print("\n✅ Successfully fetched from Prometheus")
