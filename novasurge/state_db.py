"""
novasurge/state_db.py — SQLite-backed state manager for NovaSurge.

Replaces novasurge/state/*.json files.
Tracks injections, remediations, success rates, and guardrail history.
Used by decision_engine.py for confidence scoring across rounds.

NOTE: Call init_db() explicitly once at startup (orchestrator.py does this).
      Do NOT rely on import-time side effects.
"""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta

# Resolves to novasurge/state/novasurge.db regardless of cwd
_STATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state")
DB_PATH = os.path.join(_STATE_DIR, "novasurge.db")


@contextmanager
def get_conn():
    os.makedirs(_STATE_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    """Create all tables if they don't exist. Call once at startup."""
    os.makedirs(_STATE_DIR, exist_ok=True)
    with get_conn() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS injections (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            round_num     INTEGER,
            service       TEXT NOT NULL,
            failure_type  TEXT NOT NULL,
            injected_at   TEXT NOT NULL,
            pod_target    TEXT,
            details       TEXT,
            success       INTEGER DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS remediations (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            round_num        INTEGER,
            service          TEXT NOT NULL,
            failure_type     TEXT NOT NULL,
            remediator       TEXT NOT NULL,
            attempted_at     TEXT NOT NULL,
            completed_at     TEXT,
            success          INTEGER,
            recovery_seconds REAL,
            error_message    TEXT
        );

        CREATE TABLE IF NOT EXISTS guardrail_events (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            round_num       INTEGER,
            guardrail_id    INTEGER,
            service         TEXT NOT NULL,
            blocked_action  TEXT,
            fallback_action TEXT,
            reason          TEXT,
            triggered_at    TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS round_summaries (
            round_num            INTEGER PRIMARY KEY,
            failure_type         TEXT,
            target_service       TEXT,
            injected_at          TEXT,
            anomaly_confirmed_at TEXT,
            recovered_at         TEXT,
            recovery_seconds     REAL,
            sla_target_seconds   REAL,
            sla_met              INTEGER,
            resilience_score     REAL,
            rca_result           TEXT,
            decision             TEXT,
            guardrails_triggered TEXT,
            status               TEXT DEFAULT 'IN_PROGRESS'
        );

        CREATE TABLE IF NOT EXISTS active_remediations (
            service    TEXT PRIMARY KEY,
            remediator TEXT NOT NULL,
            started_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS kv_store (
            key        TEXT PRIMARY KEY,
            value      TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """)
    print(f"[state_db] Initialized DB at {DB_PATH}")


# ── Injection tracking ────────────────────────────────────────────────────────

def record_injection(
    round_num: int,
    service: str,
    failure_type: str,
    pod_target: str = None,
    details: dict = None,
) -> None:
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO injections
               (round_num, service, failure_type, injected_at, pod_target, details)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                round_num, service, failure_type,
                datetime.utcnow().isoformat(),
                pod_target,
                json.dumps(details) if details else None,
            ),
        )


# ── Remediation tracking ──────────────────────────────────────────────────────

def record_remediation_attempt(
    round_num: int,
    service: str,
    failure_type: str,
    remediator: str,
) -> int:
    """Returns the new row id so complete_remediation() can update it."""
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO remediations
               (round_num, service, failure_type, remediator, attempted_at)
               VALUES (?, ?, ?, ?, ?)""",
            (round_num, service, failure_type, remediator,
             datetime.utcnow().isoformat()),
        )
        return cur.lastrowid


def complete_remediation(
    remediation_id: int,
    success: bool,
    recovery_seconds: float = None,
    error_message: str = None,
) -> None:
    with get_conn() as conn:
        conn.execute(
            """UPDATE remediations
               SET completed_at=?, success=?, recovery_seconds=?, error_message=?
               WHERE id=?""",
            (
                datetime.utcnow().isoformat(),
                int(success),
                recovery_seconds,
                error_message,
                remediation_id,
            ),
        )


def get_historical_success_rate(
    service: str,
    remediator: str,
    lookback_rounds: int = 10,
) -> float:
    """
    Returns float 0.0-1.0: historical success rate for (service, remediator).
    Uses a subquery to correctly limit to the last N attempts before aggregating.
    Falls back to 0.7 optimistic prior if no history exists yet.
    """
    with get_conn() as conn:
        row = conn.execute(
            """SELECT
                 COUNT(*) AS total,
                 SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) AS successes
               FROM (
                 SELECT success
                 FROM remediations
                 WHERE service = ? AND remediator = ?
                 ORDER BY id DESC
                 LIMIT ?
               )""",
            (service, remediator, lookback_rounds),
        ).fetchone()

        if not row or row["total"] == 0:
            return 0.7  # optimistic prior — no history yet
        return row["successes"] / row["total"]


def get_recent_failed_remediations(
    service: str,
    remediator: str,
    within_seconds: int = 120,
) -> bool:
    """Returns True if this remediator failed on this service within the window."""
    cutoff = (datetime.utcnow() - timedelta(seconds=within_seconds)).isoformat()
    with get_conn() as conn:
        row = conn.execute(
            """SELECT COUNT(*) AS cnt FROM remediations
               WHERE service=? AND remediator=? AND success=0
               AND attempted_at > ?""",
            (service, remediator, cutoff),
        ).fetchone()
        return row["cnt"] > 0


# ── Active remediation tracking (supports Guardrail 1) ───────────────────────

def mark_remediation_active(service: str, remediator: str) -> None:
    with get_conn() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO active_remediations
               (service, remediator, started_at)
               VALUES (?, ?, ?)""",
            (service, remediator, datetime.utcnow().isoformat()),
        )


def clear_remediation_active(service: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "DELETE FROM active_remediations WHERE service=?", (service,)
        )


def is_remediation_active(service: str) -> bool:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM active_remediations WHERE service=?", (service,)
        ).fetchone()
        return row is not None


# ── Guardrail event logging ───────────────────────────────────────────────────

def record_guardrail(
    round_num: int,
    guardrail_id: int,
    service: str,
    blocked_action: str,
    fallback_action: str,
    reason: str,
) -> None:
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO guardrail_events
               (round_num, guardrail_id, service, blocked_action,
                fallback_action, reason, triggered_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                round_num, guardrail_id, service,
                blocked_action, fallback_action, reason,
                datetime.utcnow().isoformat(),
            ),
        )


def get_guardrail_events(round_num: int) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM guardrail_events WHERE round_num=?", (round_num,)
        ).fetchall()
        return [dict(r) for r in rows]


# ── Round summary ─────────────────────────────────────────────────────────────

def upsert_round_summary(round_num: int, **kwargs) -> None:
    """Insert or update a round_summaries row. Pass column=value kwargs."""
    kwargs["round_num"] = round_num
    cols = ", ".join(kwargs.keys())
    placeholders = ", ".join(["?"] * len(kwargs))
    updates = ", ".join(
        f"{k}=excluded.{k}" for k in kwargs if k != "round_num"
    )
    with get_conn() as conn:
        conn.execute(
            f"""INSERT INTO round_summaries ({cols}) VALUES ({placeholders})
                ON CONFLICT(round_num) DO UPDATE SET {updates}""",
            list(kwargs.values()),
        )


def get_round_summary(round_num: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM round_summaries WHERE round_num=?", (round_num,)
        ).fetchone()
        return dict(row) if row else None


def get_all_round_summaries() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM round_summaries ORDER BY round_num"
        ).fetchall()
        return [dict(r) for r in rows]


# ── Generic KV store ──────────────────────────────────────────────────────────

def kv_set(key: str, value) -> None:
    with get_conn() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO kv_store (key, value, updated_at)
               VALUES (?, ?, ?)""",
            (key, json.dumps(value), datetime.utcnow().isoformat()),
        )


def kv_get(key: str, default=None):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT value FROM kv_store WHERE key=?", (key,)
        ).fetchone()
        if row:
            return json.loads(row["value"])
        return default


# ── Aggregate stats ───────────────────────────────────────────────────────────

def get_overall_stats() -> dict:
    """Aggregate stats across all rounds. Used by coverage report."""
    with get_conn() as conn:
        total = conn.execute(
            "SELECT COUNT(*) AS c FROM round_summaries"
        ).fetchone()["c"]
        met = conn.execute(
            "SELECT COUNT(*) AS c FROM round_summaries WHERE sla_met=1"
        ).fetchone()["c"]
        avg_recovery = conn.execute(
            """SELECT AVG(recovery_seconds) AS a FROM round_summaries
               WHERE recovery_seconds IS NOT NULL"""
        ).fetchone()["a"]
        guardrails = conn.execute(
            "SELECT COUNT(*) AS c FROM guardrail_events"
        ).fetchone()["c"]
        rem_success = conn.execute(
            "SELECT COUNT(*) AS c FROM remediations WHERE success=1"
        ).fetchone()["c"]
        rem_total = conn.execute(
            "SELECT COUNT(*) AS c FROM remediations"
        ).fetchone()["c"]

    return {
        "total_rounds": total,
        "sla_met_count": met,
        "sla_breach_count": total - met,
        "avg_recovery_seconds": round(avg_recovery, 2) if avg_recovery else None,
        "guardrail_triggers_total": guardrails,
        "remediation_success_rate": (
            round(rem_success / rem_total, 3) if rem_total else None
        ),
    }
