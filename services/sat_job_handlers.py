"""
SAT job handlers for the generic worker (worker.py).

Handlers:
  - sat_sync_month   — sync a specific month+direction for an issuer
  - sat_refresh_light — sync current month (issued+received)
  - sat_verify_credentials — validate FIEL is correct
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

from database import db
from services.errors import ExternalServiceError
from services.subprocess_utils import run_php
from services.sat_credentials_secure import decrypted_fiel_env

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAT_SYNC_DIR = os.path.join(BASE_DIR, "sat_sync")
PHP_SYNC = os.path.join(SAT_SYNC_DIR, "sync.php")
PHP_CHECK_FIEL = os.path.join(SAT_SYNC_DIR, "check_fiel.php")
PHP_BIN = os.environ.get("PHP_BIN", "php")

DEFAULT_BACKFILL_DAYS = int(os.environ.get("SAT_SYNC_BACKFILL_DAYS", "7"))
DEFAULT_WINDOW_HOURS = int(os.environ.get("SAT_SYNC_WINDOW_HOURS", "6"))
# Cooldown after a successful sync (seconds).  Default 6 hours.
COOLDOWN_SECONDS = int(os.environ.get("SAT_SYNC_COOLDOWN_SECONDS", "21600"))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _run_sync_php(issuer_id: int, direction: str, backfill_days: int | None = None, window_hours: int | None = None) -> tuple[bool, str]:
    """Call sync.php for one issuer+direction.  Returns (ok, message)."""
    if not os.path.isfile(PHP_SYNC):
        return False, "sync.php not found"
    env = os.environ.copy()
    env["APP_DB_PATH"] = os.environ.get("APP_DB_PATH") or os.path.join(BASE_DIR, "invoicing.db")
    bd = backfill_days if backfill_days is not None else DEFAULT_BACKFILL_DAYS
    wh = window_hours if window_hours is not None else DEFAULT_WINDOW_HOURS
    try:
        with decrypted_fiel_env(int(issuer_id)) as fiel_env:
            env.update(fiel_env)
            stdout, _stderr = run_php(
                [PHP_SYNC, str(issuer_id), direction, f"--backfill={bd}", f"--window={wh}"],
                cwd=SAT_SYNC_DIR,
                env=env,
                timeout=600,
                php_bin=PHP_BIN,
            )
        return True, (stdout or "").strip()[:500]
    except ExternalServiceError as e:
        return False, (e.internal_message or e.public_message or "Unknown error").strip()[:500]
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"[:500]


def _update_sync_state(issuer_id: int, direction: str, *, ok: bool, error_msg: str | None = None) -> None:
    """Update sat_sync_state after a sync attempt."""
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
                           last_error = NULL, cooldown_until = datetime('now', '+' || ? || ' seconds'),
                           updated_at = ?
                       WHERE issuer_id = ? AND direction = ?""",
                    (now, now, now, COOLDOWN_SECONDS, now, issuer_id, direction),
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
                    _now_iso() if not ok else None,
                    now,
                ),
            )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Handlers  (signature: (job: dict, ctx) -> dict | None)
# ---------------------------------------------------------------------------

def handle_sat_sync_month(job: dict, ctx) -> dict:
    """Sync a specific month for an issuer+direction.
    Payload: {issuer_id, direction, month?, backfill_days?, window_hours?}
    """
    payload = job.get("payload") or {}
    issuer_id = int(payload.get("issuer_id") or job.get("issuer_id"))
    direction = payload.get("direction", "issued")
    backfill = payload.get("backfill_days")
    window = payload.get("window_hours")

    ctx.progress(10, f"Sync {direction} for issuer {issuer_id}")
    ok, msg = _run_sync_php(issuer_id, direction, backfill_days=backfill, window_hours=window)
    _update_sync_state(issuer_id, direction, ok=ok, error_msg=msg if not ok else None)
    ctx.progress(100, "Done" if ok else f"Error: {msg[:80]}")

    if not ok:
        raise RuntimeError(f"SAT sync failed: {msg}")
    return {"ok": True, "message": msg}


def handle_sat_refresh_light(job: dict, ctx) -> dict:
    """Light refresh: current month issued+received for an issuer.
    Payload: {issuer_id, directions?}
    """
    payload = job.get("payload") or {}
    issuer_id = int(payload.get("issuer_id") or job.get("issuer_id"))
    directions = payload.get("directions", ["issued", "received"])

    results = {}
    for i, direction in enumerate(directions):
        ctx.progress(int((i / len(directions)) * 90) + 5, f"Sync {direction}")
        ok, msg = _run_sync_php(issuer_id, direction, backfill_days=2, window_hours=6)
        _update_sync_state(issuer_id, direction, ok=ok, error_msg=msg if not ok else None)
        results[direction] = {"ok": ok, "message": msg}

    ctx.progress(100, "Done")
    failed = [d for d, r in results.items() if not r["ok"]]
    if failed:
        raise RuntimeError(f"SAT refresh failed for: {', '.join(failed)}")
    return {"ok": True, "results": results}


def handle_sat_verify_credentials(job: dict, ctx) -> dict:
    """Validate FIEL credentials for an issuer.
    Payload: {issuer_id}
    """
    payload = job.get("payload") or {}
    issuer_id = int(payload.get("issuer_id") or job.get("issuer_id"))

    if not os.path.isfile(PHP_CHECK_FIEL):
        raise RuntimeError("check_fiel.php not found")

    env = os.environ.copy()
    env["APP_DB_PATH"] = os.environ.get("APP_DB_PATH") or os.path.join(BASE_DIR, "invoicing.db")

    ctx.progress(10, "Validating FIEL")
    try:
        with decrypted_fiel_env(int(issuer_id)) as fiel_env:
            env.update(fiel_env)
            stdout, _stderr = run_php(
                [PHP_CHECK_FIEL, str(issuer_id)],
                cwd=BASE_DIR,
                env=env,
                timeout=30,
                php_bin=PHP_BIN,
            )
        ctx.progress(100, "FIEL validated")
        return {"ok": True, "message": (stdout or "").strip()[:200]}
    except ExternalServiceError as e:
        msg = (e.internal_message or e.public_message or "Error")[:200]
        raise RuntimeError(f"FIEL validation failed: {msg}")
