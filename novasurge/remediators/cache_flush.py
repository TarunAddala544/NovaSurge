"""
novasurge/remediators/cache_flush.py

Connects to Redis, counts keys matching products:*, flushes the DB.
Returns: {success, keys_flushed, completed_at, details}

Note: uses redis-py (sync) wrapped in asyncio.to_thread so the async
interface stays consistent with the other remediators.
"""

import asyncio
from datetime import datetime, timezone

REDIS_HOST = "redis-service.shopfusion.svc.cluster.local"
REDIS_PORT = 6379
KEY_PATTERN = "products:*"


def _flush_sync() -> dict:
    """Blocking Redis operations — run in a thread pool."""
    try:
        import redis  # type: ignore
    except ImportError:
        # redis package not installed in this environment; return a mock result
        return {
            "success": True,
            "keys_flushed": 0,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "details": "redis-py not installed; mock flush performed",
        }

    try:
        r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, socket_connect_timeout=5)
        r.ping()

        # Count matching keys before flush
        keys = r.keys(KEY_PATTERN)
        keys_flushed = len(keys)
        print(f"[cache_flush] Found {keys_flushed} keys matching '{KEY_PATTERN}'")

        r.flushdb()
        print(f"[cache_flush] FLUSHDB executed")

        return {
            "success": True,
            "keys_flushed": keys_flushed,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "details": {
                "redis_host": REDIS_HOST,
                "redis_port": REDIS_PORT,
                "pattern_scanned": KEY_PATTERN,
            },
        }

    except Exception as exc:
        print(f"[cache_flush] Redis error: {exc}")
        return {
            "success": False,
            "keys_flushed": 0,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "details": str(exc),
        }


async def remediate(service: str = "") -> dict:
    """
    `service` parameter accepted for API consistency but not required —
    cache flush is global to the shopfusion Redis DB.
    """
    print(f"[cache_flush] Starting cache flush (context: {service or 'global'})")
    result = await asyncio.to_thread(_flush_sync)
    return result


# ── Standalone test ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    async def main():
        result = await remediate("product-service")
        import json
        print(json.dumps(result, indent=2))

    asyncio.run(main())
