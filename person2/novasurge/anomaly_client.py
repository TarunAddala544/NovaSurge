"""
novasurge/anomaly_client.py

Wraps Person 3's anomaly detection endpoint.
Uses MockAnomalyEndpoint (with 20s delay) until the real endpoint is live.

Toggle: set NOVASURGE_MOCK_ANOMALY=false once Person 3's service is up.
"""

import os
import asyncio
import logging
import time
import random
from datetime import datetime, timezone
from typing import Optional

import httpx

logger = logging.getLogger("novasurge.anomaly_client")

USE_MOCK: bool = os.environ.get("NOVASURGE_MOCK_ANOMALY", "true").lower() == "true"
ANOMALY_ENDPOINT: str = os.environ.get("ANOMALY_ENDPOINT", "http://localhost:8000/anomaly/current")

SERVICES = [
    "api-gateway",
    "product-service",
    "order-service",
    "payment-service",
    "notification-service",
]

ANOMALY_TYPES = [
    "pod_crash",
    "oom_kill",
    "cpu_throttle",
    "network_partition",
    "replica_exhaustion",
    "cache_miss_spike",
    "high_latency",
]


# ─── Mock ─────────────────────────────────────────────────────────────────────

class MockAnomalyEndpoint:
    """
    Returns a realistic anomaly payload after a 20-second delay.
    The caller passes the expected service/type so the mock is coherent
    with what was just injected.
    """

    async def fetch(
        self,
        expected_service: Optional[str] = None,
        expected_type: Optional[str] = None,
    ) -> dict:
        logger.info("[MOCK] MockAnomalyEndpoint: waiting 20 seconds to simulate detection latency...")
        print("[MOCK] MockAnomalyEndpoint: waiting 20s for detection...")
        await asyncio.sleep(20)

        service = expected_service or random.choice(SERVICES)
        anomaly_type = expected_type or random.choice(ANOMALY_TYPES)
        severity = round(random.uniform(0.55, 0.95), 2)

        payload = {
            "anomaly_detected": True,
            "affected_service": service,
            "anomaly_type": anomaly_type,
            "severity_score": severity,
            "feature_deltas": {
                "p99_latency": round(random.uniform(1.5, 6.0), 2),
                "error_rate": round(random.uniform(0.05, 0.35), 2),
            },
            "_mock": True,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        logger.info(f"[MOCK] Anomaly payload generated: {payload}")
        print(f"[MOCK] Anomaly detected: {payload}")
        return payload


# ─── Real client ──────────────────────────────────────────────────────────────

async def _fetch_real() -> dict:
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(ANOMALY_ENDPOINT)
        resp.raise_for_status()
        return resp.json()


# ─── Public API ───────────────────────────────────────────────────────────────

async def fetch_anomaly(
    expected_service: Optional[str] = None,
    expected_type: Optional[str] = None,
) -> dict:
    if USE_MOCK:
        return await MockAnomalyEndpoint().fetch(expected_service, expected_type)
    return await _fetch_real()


async def poll_for_anomaly(
    timeout_seconds: int = 60,
    poll_interval: int = 5,
    expected_service: Optional[str] = None,
    expected_type: Optional[str] = None,
) -> Optional[dict]:
    """
    Poll the anomaly endpoint every poll_interval seconds.
    Returns the first payload where anomaly_detected=True.
    Returns None on timeout.
    """
    deadline = time.monotonic() + timeout_seconds
    attempt = 0

    while time.monotonic() < deadline:
        attempt += 1
        try:
            payload = await fetch_anomaly(expected_service, expected_type)
            if payload.get("anomaly_detected"):
                logger.info(f"Anomaly confirmed on attempt {attempt}: {payload}")
                return payload
            else:
                logger.debug(f"Attempt {attempt}: no anomaly yet, retrying in {poll_interval}s")
        except Exception as exc:
            logger.warning(f"Attempt {attempt}: anomaly fetch failed ({exc}), retrying...")

        await asyncio.sleep(poll_interval)

    logger.error(f"poll_for_anomaly timed out after {timeout_seconds}s")
    return None


# ─── Metrics snapshot helper ──────────────────────────────────────────────────

def build_mock_metrics_snapshot(anomaly_payload: dict) -> dict:
    """
    Builds a plausible metrics snapshot for all services.
    The affected_service is given elevated metrics; others are normal.
    Used by rca.analyze() and decision_engine.decide().
    """
    affected = anomaly_payload.get("affected_service", "order-service")
    deltas = anomaly_payload.get("feature_deltas", {})

    snapshot = {}
    for svc in SERVICES:
        if svc == affected:
            snapshot[svc] = {
                "p99_latency": 200 + deltas.get("p99_latency", 1.0) * 100,
                "error_rate": 0.02 + deltas.get("error_rate", 0.05),
                "http_request_rate": random.uniform(40, 80),
                "baseline_request_rate": 50.0,
                "replica_count": random.randint(1, 2),
                "deviation_window": 0,  # first to deviate
            }
        else:
            snapshot[svc] = {
                "p99_latency": random.uniform(20, 80),
                "error_rate": random.uniform(0.001, 0.01),
                "http_request_rate": random.uniform(30, 60),
                "baseline_request_rate": 50.0,
                "replica_count": random.randint(2, 4),
                "deviation_window": random.randint(1, 4),  # deviated later
            }

    return snapshot
