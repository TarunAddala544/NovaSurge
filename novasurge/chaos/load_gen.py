"""
novasurge/chaos/load_gen.py

Continuous realistic traffic generator for the ShopFusion api-gateway.
Sends 50 requests/second (configurable) with the following distribution:
  40% GET /products/{id}      (product id 1-20)
  25% POST /orders            (random product, quantity 1-5)
  20% GET /orders/{id}        (random existing order)
  15% GET /payments/{id}      (random existing payment)

Usage:
  python load_gen.py --host localhost:30080 --rps 50

Logs request rate and error rate every 10 seconds.
Runs until killed (Ctrl+C).
"""

import argparse
import asyncio
import logging
import random
import signal
import sys
import time
from collections import deque
from datetime import datetime, timezone

import httpx

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("novasurge.load_gen")

# ─── Shared state ─────────────────────────────────────────────────────────────

_counters = {
    "total": 0,
    "success": 0,
    "error": 0,
    "by_endpoint": {
        "GET /products": {"total": 0, "error": 0},
        "POST /orders": {"total": 0, "error": 0},
        "GET /orders": {"total": 0, "error": 0},
        "GET /payments": {"total": 0, "error": 0},
    },
}
_window_start = time.monotonic()
_window_total = 0
_window_errors = 0

# Keep a deque of recent order/payment IDs to simulate realistic reads
_known_order_ids: deque = deque(maxlen=100)
_known_payment_ids: deque = deque(maxlen=100)


# ─── Request builders ─────────────────────────────────────────────────────────

def _get_products_request(base_url: str) -> tuple[str, str, dict]:
    pid = random.randint(1, 20)
    return "GET", f"{base_url}/products/{pid}", {}


def _post_orders_request(base_url: str) -> tuple[str, str, dict]:
    payload = {
        "product_id": random.randint(1, 20),
        "quantity": random.randint(1, 5),
        "customer_id": f"cust-{random.randint(1000, 9999)}",
    }
    return "POST", f"{base_url}/orders", {"json": payload}


def _get_orders_request(base_url: str) -> tuple[str, str, dict]:
    if _known_order_ids:
        oid = random.choice(_known_order_ids)
    else:
        oid = random.randint(1, 50)
    return "GET", f"{base_url}/orders/{oid}", {}


def _get_payments_request(base_url: str) -> tuple[str, str, dict]:
    if _known_payment_ids:
        pid = random.choice(_known_payment_ids)
    else:
        pid = random.randint(1, 50)
    return "GET", f"{base_url}/payments/{pid}", {}


def _pick_request(base_url: str) -> tuple[str, str, str, dict]:
    """Return (endpoint_label, method, url, kwargs) based on distribution."""
    roll = random.random()
    if roll < 0.40:
        m, u, kw = _get_products_request(base_url)
        return "GET /products", m, u, kw
    elif roll < 0.65:
        m, u, kw = _post_orders_request(base_url)
        return "POST /orders", m, u, kw
    elif roll < 0.85:
        m, u, kw = _get_orders_request(base_url)
        return "GET /orders", m, u, kw
    else:
        m, u, kw = _get_payments_request(base_url)
        return "GET /payments", m, u, kw


# ─── Core request sender ──────────────────────────────────────────────────────

async def _send_request(client: httpx.AsyncClient, base_url: str) -> None:
    global _window_total, _window_errors

    label, method, url, kwargs = _pick_request(base_url)
    _counters["total"] += 1
    _counters["by_endpoint"][label]["total"] += 1
    _window_total += 1

    try:
        if method == "GET":
            resp = await client.get(url, timeout=5.0)
        else:
            resp = await client.post(url, timeout=5.0, **kwargs)

        if resp.status_code < 400:
            _counters["success"] += 1
            # Harvest IDs from responses
            try:
                body = resp.json()
                if label == "POST /orders" and "id" in body:
                    _known_order_ids.append(body["id"])
                    if "payment_id" in body:
                        _known_payment_ids.append(body["payment_id"])
            except Exception:
                pass
        else:
            _counters["error"] += 1
            _counters["by_endpoint"][label]["error"] += 1
            _window_errors += 1
            logger.debug(f"HTTP {resp.status_code} {method} {url}")

    except (httpx.RequestError, httpx.TimeoutException) as exc:
        _counters["error"] += 1
        _counters["by_endpoint"][label]["error"] += 1
        _window_errors += 1
        logger.debug(f"Request failed {method} {url}: {exc}")


# ─── Stats reporter ───────────────────────────────────────────────────────────

async def _stats_reporter(report_interval: int = 10) -> None:
    global _window_start, _window_total, _window_errors
    while True:
        await asyncio.sleep(report_interval)
        elapsed = time.monotonic() - _window_start
        rps = _window_total / elapsed if elapsed > 0 else 0
        err_rate = (_window_errors / _window_total * 100) if _window_total > 0 else 0.0

        logger.info(
            f"[stats] rps={rps:.1f}  "
            f"total={_counters['total']}  "
            f"errors={_counters['error']}  "
            f"error_rate={err_rate:.2f}%  "
            f"by_endpoint={{ "
            + "  ".join(
                f"{k}: ok={v['total']-v['error']} err={v['error']}"
                for k, v in _counters["by_endpoint"].items()
            )
            + " }"
        )

        # Reset window
        _window_start = time.monotonic()
        _window_total = 0
        _window_errors = 0


# ─── Main loop ────────────────────────────────────────────────────────────────

async def run(host: str, rps: int) -> None:
    base_url = f"http://{host}"
    interval = 1.0 / rps  # seconds between spawns

    logger.info(f"NovaSurge Load Generator starting")
    logger.info(f"  Target:  {base_url}")
    logger.info(f"  Rate:    {rps} req/s")
    logger.info(f"  Mix:     40% GET /products  25% POST /orders  20% GET /orders  15% GET /payments")
    logger.info(f"  Press Ctrl+C to stop")

    # Start stats reporter as background task
    asyncio.create_task(_stats_reporter(10))

    limits = httpx.Limits(max_keepalive_connections=50, max_connections=100)
    async with httpx.AsyncClient(limits=limits) as client:
        while True:
            asyncio.create_task(_send_request(client, base_url))
            await asyncio.sleep(interval)


def _handle_sigint(sig, frame):
    total = _counters["total"]
    errors = _counters["error"]
    err_pct = (errors / total * 100) if total > 0 else 0.0
    print(f"\n\nLoad generator stopped.")
    print(f"  Total requests : {total}")
    print(f"  Errors         : {errors} ({err_pct:.2f}%)")
    sys.exit(0)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="NovaSurge Load Generator")
    parser.add_argument("--host", default="localhost:30080", help="api-gateway host:port")
    parser.add_argument("--rps", type=int, default=50, help="Requests per second")
    args = parser.parse_args()

    signal.signal(signal.SIGINT, _handle_sigint)
    asyncio.run(run(args.host, args.rps))
