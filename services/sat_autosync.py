"""
SAT auto-sync helpers: enqueue sat_jobs with dedupe and cooldown management.

Works with the existing sat_jobs table (processed by scripts/sat_worker.py).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from database import db, has_column, table_exists

logger = logging.getLogger(__name__)

# Dedupe window: don't enqueue if a job for same issuer+direction was
# created within this many hours and is still queued/running.
DEDUPE_WINDOW_HOURS = 2


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def enqueue_sat_sync(
    issuer_id: int,
    direction: str,
    *,
    job_type: str = "xml",
    dry_run: bool = False,
) -> int | None:
    """Enqueue a sat_jobs entry with dedupe.  Returns job id or None if skipped."""
    if direction not in ("issued", "received"):
        raise ValueError(f"Invalid direction: {direction}")

    conn = db()
    try:
        # Dedupe: skip if recent queued/running job exists
        existing = conn.execute(
            """SELECT id FROM sat_jobs
               WHERE issuer_id = ? AND direction = ? AND status IN ('queued','running')
                 AND created_at > datetime('now', '-' || ? || ' hours')
               LIMIT 1""",
            (issuer_id, direction, DEDUPE_WINDOW_HOURS),
        ).fetchone()
        if existing:
            eid = existing["id"] if isinstance(existing, dict) else existing[0]
            logger.debug("Skipping enqueue issuer=%s dir=%s: existing job %s", issuer_id, direction, eid)
            return None

        if dry_run:
            logger.info("[dry-run] Would enqueue issuer=%s dir=%s", issuer_id, direction)
            return -1

        conn.execute(
            """INSERT INTO sat_jobs (issuer_id, job_type, direction, status, created_at, updated_at)
               VALUES (?, ?, ?, 'queued', datetime('now'), datetime('now'))""",
            (issuer_id, job_type, direction),
        )
        conn.commit()
        job_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        logger.info("Enqueued sat_jobs id=%s issuer=%s dir=%s", job_id, issuer_id, direction)
        return job_id
    finally:
        conn.close()


def enqueue_onboarding_sync(issuer_id: int) -> list[int]:
    """Enqueue initial sync (current + previous month, issued + received).
    Returns list of created job ids.
    """
    ids = []
    for direction in ("issued", "received"):
        jid = enqueue_sat_sync(issuer_id, direction, job_type="xml")
        if jid:
            ids.append(jid)
    return ids


def get_eligible_issuers(
    *,
    cooldown_hours: int = 8,
    batch: int = 50,
    active_days: int = 30,
    directions: list[str] | None = None,
) -> list[dict]:
    """Return issuers eligible for auto-sync.

    Filters by: valid FIEL, active issuer, recent login (within active_days)
    or active plan, cooldown expired, no recent queued/running jobs.
    Returns list of {issuer_id, rfc, direction} dicts.
    """
    if directions is None:
        directions = ["issued", "received"]

    conn = db()
    try:
        results = []
        for direction in directions:
            rows = conn.execute(
                """
                SELECT sc.issuer_id, i.rfc
                FROM sat_credentials sc
                JOIN issuers i ON i.id = sc.issuer_id AND i.active = 1
                LEFT JOIN sat_sync_state ss
                  ON ss.issuer_id = sc.issuer_id AND ss.direction = ?
                WHERE sc.validation_ok = 1
                  AND (ss.cooldown_until IS NULL OR ss.cooldown_until < datetime('now'))
                  AND NOT EXISTS (
                    SELECT 1 FROM sat_jobs sj
                    WHERE sj.issuer_id = sc.issuer_id
                      AND sj.direction = ?
                      AND sj.status IN ('queued','running')
                      AND sj.created_at > datetime('now', '-' || ? || ' hours')
                  )
                  AND (
                    -- Active within active_days: recent audit activity or active plan
                    EXISTS (
                      SELECT 1 FROM audit_log al
                      JOIN memberships m ON m.user_id = al.user_id AND m.issuer_id = sc.issuer_id
                      WHERE al.created_at > datetime('now', '-' || ? || ' days')
                      LIMIT 1
                    )
                    OR EXISTS (
                      SELECT 1 FROM subscriptions s
                      WHERE s.issuer_id = sc.issuer_id
                        AND s.status IN ('active', 'trialing')
                    )
                  )
                ORDER BY COALESCE(ss.last_success_at, '2000-01-01') ASC
                LIMIT ?
                """,
                (direction, direction, DEDUPE_WINDOW_HOURS, active_days, batch),
            ).fetchall()
            for row in rows:
                iid = row["issuer_id"] if isinstance(row, dict) else row[0]
                rfc = row["rfc"] if isinstance(row, dict) else row[1]
                results.append({"issuer_id": iid, "rfc": rfc, "direction": direction})
        return results
    finally:
        conn.close()


def update_sync_state_after_job(
    issuer_id: int, direction: str, *, ok: bool, error_msg: str | None = None,
    cooldown_hours: int = 8,
) -> None:
    """Update sat_sync_state after a sat_jobs completes.  Called by sat_worker."""
    now = _now_iso()
    conn = db()
    try:
        existing = conn.execute(
            "SELECT id FROM sat_sync_state WHERE issuer_id = ? AND direction = ?",
            (issuer_id, direction),
        ).fetchone()
        if existing:
            if ok:
                conn.execute(
                    """UPDATE sat_sync_state
                       SET last_attempt_at = ?, last_success_at = ?, last_run_at = ?,
                           last_error = NULL,
                           cooldown_until = datetime('now', '+' || ? || ' hours'),
                           updated_at = ?
                       WHERE issuer_id = ? AND direction = ?""",
                    (now, now, now, cooldown_hours, now, issuer_id, direction),
                )
            else:
                conn.execute(
                    """UPDATE sat_sync_state
                       SET last_attempt_at = ?, last_error = ?, updated_at = ?
                       WHERE issuer_id = ? AND direction = ?""",
                    (now, error_msg, now, issuer_id, direction),
                )
        else:
            conn.execute(
                """INSERT INTO sat_sync_state
                   (issuer_id, direction, last_attempt_at, last_success_at, last_run_at,
                    last_error, cooldown_until, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    issuer_id, direction, now,
                    now if ok else None,
                    now if ok else None,
                    None if ok else error_msg,
                    None,
                    now,
                ),
            )
        conn.commit()
    finally:
        conn.close()
