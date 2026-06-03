"""
SAT auto-sync helpers: enqueue sat_jobs with dedupe and cooldown management.

Works with the existing sat_jobs table (processed by scripts/sat_worker.py).
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone

from database import db

logger = logging.getLogger(__name__)

# Dedupe window: don't enqueue if a job for same issuer+direction was
# created within this many hours and is still queued/running.
DEDUPE_WINDOW_HOURS = 2

# ── Anti-colapso: capacity limits ──
MAX_JOBS_PER_HOUR = 60  # Global: max new sat_jobs per hour
MAX_JOBS_PER_ISSUER_PER_DAY = 10  # Per-issuer: max jobs per day

# Exponential backoff on error: cooldown increases with consecutive failures
BACKOFF_SCHEDULE_MINUTES = [30, 120, 1440]  # 30 min → 2 hours → 24 hours


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def enqueue_sat_sync(
    issuer_id: int,
    direction: str,
    *,
    job_type: str = "xml",
    dry_run: bool = False,
    priority: int = 100,
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

        # Anti-colapso: global rate limit
        global_count = conn.execute(
            "SELECT COUNT(*) AS n FROM sat_jobs WHERE created_at > datetime('now', '-1 hour')",
        ).fetchone()
        if global_count and (global_count["n"] if isinstance(global_count, dict) else global_count[0]) >= MAX_JOBS_PER_HOUR:
            logger.warning("Global rate limit reached (%d jobs/hour). Skipping issuer=%s", MAX_JOBS_PER_HOUR, issuer_id)
            return None

        # Anti-colapso: per-issuer daily limit
        issuer_count = conn.execute(
            "SELECT COUNT(*) AS n FROM sat_jobs WHERE issuer_id = ? AND created_at > datetime('now', '-24 hours')",
            (issuer_id,),
        ).fetchone()
        if issuer_count and (issuer_count["n"] if isinstance(issuer_count, dict) else issuer_count[0]) >= MAX_JOBS_PER_ISSUER_PER_DAY:
            logger.warning("Per-issuer daily limit reached (%d/day) for issuer=%s. Skipping.", MAX_JOBS_PER_ISSUER_PER_DAY, issuer_id)
            return None

        if dry_run:
            logger.info("[dry-run] Would enqueue issuer=%s dir=%s", issuer_id, direction)
            return -1

        conn.execute(
            """INSERT INTO sat_jobs (issuer_id, job_type, direction, status, priority, created_at, updated_at)
               VALUES (?, ?, ?, 'queued', ?, datetime('now'), datetime('now'))""",
            (issuer_id, job_type, direction, priority),
        )
        conn.commit()
        job_id = conn.execute("SELECT last_insert_rowid() AS rid").fetchone()["rid"]
        logger.info("Enqueued sat_jobs id=%s issuer=%s dir=%s", job_id, issuer_id, direction)
        return job_id
    finally:
        conn.close()


def default_history_option() -> str:
    """Return the smart default history option based on current date.

    If Jan-Mar: 'last_3_months' (just getting started, keep it light).
    If Apr+: 'current_year' (need data since January for annual tax prep).
    """
    from datetime import date
    if date.today().month <= 3:
        return "last_3_months"
    return "current_year"


def history_option_to_start_date(option: str) -> str:
    """Convert a history option to a start date string (YYYY-MM-DD).

    Args:
        option: One of 'last_3_months', 'current_year', 'last_12_months', 'full_5_years'.

    Returns:
        ISO date string for the first day of the starting month.
    """
    from datetime import date
    from dateutil.relativedelta import relativedelta
    today = date.today()
    if option == "last_3_months":
        start = today - relativedelta(months=3)
    elif option == "current_year":
        start = date(today.year, 1, 1)
    elif option == "last_12_months":
        start = today - relativedelta(months=12)
    elif option == "full_5_years":
        start = today - relativedelta(years=5)
    else:
        start = today - relativedelta(months=3)
    return date(start.year, start.month, 1).isoformat()


def enqueue_onboarding_sync(issuer_id: int) -> list[int]:
    """Enqueue initial sync (current + previous month, issued + received).
    Returns list of created job ids.
    """
    ids = []
    for direction in ("issued", "received"):
        jid = enqueue_sat_sync(issuer_id, direction, job_type="xml", priority=1)
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
                iid = row["issuer_id"]
                rfc = row["rfc"]
                results.append({"issuer_id": iid, "rfc": rfc, "direction": direction})
        return results
    finally:
        conn.close()


def _consecutive_failures(conn, issuer_id: int, direction: str) -> int:
    """Count consecutive recent error jobs for backoff calculation."""
    rows = conn.execute(
        """SELECT status FROM sat_jobs
           WHERE issuer_id = ? AND direction = ? AND status IN ('ok','error')
           ORDER BY id DESC LIMIT 10""",
        (issuer_id, direction),
    ).fetchall()
    count = 0
    for row in rows:
        st = row["status"]
        if st == "error":
            count += 1
        else:
            break
    return count


def _backoff_minutes(consecutive_failures: int) -> int:
    """Return cooldown minutes based on consecutive failures (exponential backoff)."""
    if consecutive_failures <= 0:
        return 0
    idx = min(consecutive_failures - 1, len(BACKOFF_SCHEDULE_MINUTES) - 1)
    return BACKOFF_SCHEDULE_MINUTES[idx]


def update_sync_state_after_job(
    issuer_id: int, direction: str, *, ok: bool, error_msg: str | None = None,
    cooldown_hours: int = 8,
) -> None:
    """Update sat_sync_state after a sat_jobs completes.  Called by sat_worker.
    On success: standard cooldown. On error: exponential backoff (30m → 2h → 24h).
    """
    now = _now_iso()
    conn = db()
    try:
        # On error, calculate backoff from consecutive failures
        if not ok:
            failures = _consecutive_failures(conn, issuer_id, direction)
            backoff_min = _backoff_minutes(failures)
            cooldown_expr = f"+{backoff_min} minutes" if backoff_min > 0 else None
        else:
            cooldown_expr = f"+{cooldown_hours} hours"

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
                           cooldown_until = datetime('now', ?),
                           updated_at = ?
                       WHERE issuer_id = ? AND direction = ?""",
                    (now, now, now, cooldown_expr, now, issuer_id, direction),
                )
            else:
                if cooldown_expr:
                    conn.execute(
                        """UPDATE sat_sync_state
                           SET last_attempt_at = ?, last_error = ?,
                               cooldown_until = datetime('now', ?),
                               updated_at = ?
                           WHERE issuer_id = ? AND direction = ?""",
                        (now, error_msg, cooldown_expr, now, issuer_id, direction),
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
        if not ok:
            failures = _consecutive_failures(conn, issuer_id, direction)
            backoff = _backoff_minutes(failures)
            logger.info(
                "Sync error issuer=%s dir=%s failures=%d backoff=%dmin",
                issuer_id, direction, failures, backoff,
            )
    finally:
        conn.close()


# ── Multi-tier cron helpers ──────────────────────────────────────────


def _get_fiel_issuers() -> list[int]:
    """Return issuer_ids with validated FIEL credentials."""
    conn = db()
    try:
        rows = conn.execute(
            "SELECT DISTINCT sc.issuer_id FROM sat_credentials sc "
            "JOIN issuers i ON i.id = sc.issuer_id AND i.active = 1 "
            "WHERE sc.validation_ok = 1"
        ).fetchall()
        return [r["issuer_id"] for r in rows]
    finally:
        conn.close()


def _ym_range(months_back: int) -> list[str]:
    """Return list of YYYY-MM strings from current month back N months."""
    from dateutil.relativedelta import relativedelta
    today = date.today()
    result = []
    for i in range(months_back):
        d = today - relativedelta(months=i)
        result.append(f"{d.year:04d}-{d.month:02d}")
    return result


def enqueue_active_issuers_current_month() -> int:
    """Enqueue sync for current month of all issuers with validated FIEL.

    Called by hourly cron. Uses smart priority (current month = urgent).
    Returns number of jobs enqueued.
    """
    from services.sat.sat_priority import compute_priority, is_user_active_recently

    issuers = _get_fiel_issuers()
    ym = _ym_range(1)[0]
    count = 0
    for iid in issuers:
        active = is_user_active_recently(iid)
        prio = compute_priority(iid, ym, user_active_recently=active)
        for direction in ("issued", "received"):
            jid = enqueue_sat_sync(iid, direction, priority=prio)
            if jid and jid > 0:
                count += 1
    return count


def enqueue_active_issuers_last_3_months() -> int:
    """Enqueue sync for last 3 months of all issuers with validated FIEL.

    Called by daily cron. Priority decreases for older months.
    Returns number of jobs enqueued.
    """
    from services.sat.sat_priority import compute_priority, is_user_active_recently

    issuers = _get_fiel_issuers()
    yms = _ym_range(3)
    count = 0
    for iid in issuers:
        active = is_user_active_recently(iid)
        for ym in yms:
            prio = compute_priority(iid, ym, user_active_recently=active)
            for direction in ("issued", "received"):
                jid = enqueue_sat_sync(iid, direction, priority=prio)
                if jid and jid > 0:
                    count += 1
    return count


def enqueue_active_issuers_last_6_months() -> int:
    """Enqueue sync for last 6 months of all issuers with validated FIEL.

    Called by weekly cron. Deep backfill with low priority for old months.
    Returns number of jobs enqueued.
    """
    from services.sat.sat_priority import compute_priority, is_user_active_recently

    issuers = _get_fiel_issuers()
    yms = _ym_range(6)
    count = 0
    for iid in issuers:
        active = is_user_active_recently(iid)
        for ym in yms:
            prio = compute_priority(iid, ym, user_active_recently=active)
            for direction in ("issued", "received"):
                jid = enqueue_sat_sync(iid, direction, priority=prio)
                if jid and jid > 0:
                    count += 1
    return count
