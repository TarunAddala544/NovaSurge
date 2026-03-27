"""
novasurge/state_manager.py

Thread-safe (file-level) state management for:
  - active_remediations.json    (guardrail 1)
  - remediation_history.json    (guardrail 3)
  - round_status.json           (orchestrator status board)
"""

import json
import os
import time
import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("novasurge.state_manager")

STATE_DIR = os.path.join(os.path.dirname(__file__), "state")
os.makedirs(STATE_DIR, exist_ok=True)

ACTIVE_FILE = os.path.join(STATE_DIR, "active_remediations.json")
HISTORY_FILE = os.path.join(STATE_DIR, "remediation_history.json")
ROUND_STATUS_FILE = os.path.join(STATE_DIR, "round_status.json")


def _load(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save(path: str, data: dict) -> None:
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


# ─── Active remediations (Guardrail 1) ───────────────────────────────────────

def mark_active(service: str, remediation: str) -> None:
    data = _load(ACTIVE_FILE)
    data[service] = {
        "remediation": remediation,
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    _save(ACTIVE_FILE, data)
    logger.info(f"[State] Active remediation registered: {service} → {remediation}")


def clear_active(service: str) -> None:
    data = _load(ACTIVE_FILE)
    data.pop(service, None)
    _save(ACTIVE_FILE, data)
    logger.info(f"[State] Active remediation cleared: {service}")


def is_active(service: str) -> bool:
    return service in _load(ACTIVE_FILE)


def get_active_count() -> int:
    return len(_load(ACTIVE_FILE))


def get_all_active_services() -> list:
    return list(_load(ACTIVE_FILE).keys())


# ─── Remediation history (Guardrail 3) ───────────────────────────────────────

def record_remediation_result(
    service: str,
    remediation: str,
    success: bool,
    timestamp: Optional[float] = None,
) -> None:
    data = _load(HISTORY_FILE)
    key = f"{service}::{remediation}"
    if key not in data:
        data[key] = []
    data[key].append({
        "success": success,
        "ts": timestamp or time.time(),
    })
    # keep last 20 entries per key
    data[key] = data[key][-20:]
    _save(HISTORY_FILE, data)


def was_recently_failed(service: str, remediation: str, window_seconds: int = 120) -> bool:
    data = _load(HISTORY_FILE)
    key = f"{service}::{remediation}"
    entries = data.get(key, [])
    cutoff = time.time() - window_seconds
    for entry in reversed(entries):
        if entry["ts"] >= cutoff and not entry["success"]:
            return True
    return False


# ─── Round status board ───────────────────────────────────────────────────────

VALID_STATUSES = {
    "INJECTING", "DETECTING", "ANALYZING",
    "DECIDING", "RECOVERING", "HEALTHY", "FAILED",
}


def write_round_status(round_num: int, status: str, extra: Optional[dict] = None) -> None:
    if status not in VALID_STATUSES:
        raise ValueError(f"Invalid status: {status}. Must be one of {VALID_STATUSES}")
    payload = {
        "round": round_num,
        "status": status,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        **(extra or {}),
    }
    _save(ROUND_STATUS_FILE, payload)
    logger.info(f"[State] Round {round_num} → {status}")
    print(f"  ⟳  Round {round_num} status: {status}")


def read_round_status() -> dict:
    return _load(ROUND_STATUS_FILE)
