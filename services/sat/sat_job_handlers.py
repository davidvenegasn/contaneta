"""
SAT job handlers for the generic worker (worker.py).

Handlers:
  - sat_sync_month   — sync a specific month+direction for an issuer
  - sat_refresh_light — sync current month (issued+received)
  - sat_verify_credentials — validate FIEL is correct
  - sat_xml_backfill — retry XML download for CFDIs missing xml_path
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

from database import db
from services.errors import ExternalServiceError
from services.sat.sat_credentials_secure import decrypted_fiel_env
from services.sat.subprocess_utils import run_php

logger = logging.getLogger(__name__)

import time

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAT_SYNC_DIR = os.path.join(BASE_DIR, "sat_sync")
PHP_SYNC = os.path.join(SAT_SYNC_DIR, "sync.php")
PHP_SYNC_XML = os.path.join(SAT_SYNC_DIR, "sync_xml.php")
PHP_VERIFY = os.path.join(SAT_SYNC_DIR, "verify_requests.php")
PHP_PARSE_XML = os.path.join(SAT_SYNC_DIR, "parse_xml.php")
PHP_CHECK_FIEL = os.path.join(SAT_SYNC_DIR, "check_fiel.php")
PHP_BIN = os.environ.get("PHP_BIN", "php")

DEFAULT_BACKFILL_DAYS = int(os.environ.get("SAT_SYNC_BACKFILL_DAYS", "7"))
DEFAULT_WINDOW_HOURS = int(os.environ.get("SAT_SYNC_WINDOW_HOURS", "6"))
# Cooldown after a successful sync (seconds).  Default 2 hours.
COOLDOWN_SECONDS = int(os.environ.get("SAT_SYNC_COOLDOWN_SECONDS", "7200"))


# ---------------------------------------------------------------------------
# Error categorization for retry strategy
# ---------------------------------------------------------------------------

def classify_sat_error(error_msg: str) -> str:
    """Categorize SAT errors to decide retry strategy.

    Returns one of: 'network', 'empty', 'rate_limit', 'auth', 'sat_5xx', 'unknown'.
    """
    msg = (error_msg or "").lower()
    if any(s in msg for s in ["could not resolve host", "connection refused",
                               "timeout", "timed out", "network", "dns"]):
        return "network"
    if "sin información" in msg or "no_records" in msg or "no records" in msg:
        return "empty"
    if "rate" in msg or "too many" in msg or "429" in msg:
        return "rate_limit"
    if "unauthorized" in msg or "401" in msg or "fiel" in msg and "invalid" in msg:
        return "auth"
    if "500" in msg or "internal server" in msg or "502" in msg or "503" in msg:
        return "sat_5xx"
    return "unknown"


# Retry delays per error category (seconds). Index = attempt number.
RETRY_DELAYS = {
    "network": [300, 900, 3600, 21600],      # 5min, 15min, 1h, 6h
    "empty": [3600, 21600, 86400],            # 1h, 6h, 24h
    "rate_limit": [3600, 7200, 14400],        # 1h, 2h, 4h
    "sat_5xx": [600, 1800, 7200],             # 10min, 30min, 2h
    "unknown": [1800, 7200, 86400],           # 30min, 2h, 24h
    "auth": [],                               # no retry — manual fix needed
}


def get_max_attempts_for_category(category: str) -> int:
    """Return max retry attempts for an error category."""
    return len(RETRY_DELAYS.get(category, [])) + 1  # +1 for initial attempt


def should_retry(category: str, attempt: int) -> bool:
    """Return True if this error category allows retrying at this attempt."""
    delays = RETRY_DELAYS.get(category, [])
    return attempt < len(delays)


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


def _run_xml_pipeline(issuer_id: int, direction: str, *, backfill_days: int = 7, window_hours: int = 6, month: str | None = None) -> tuple[bool, str]:
    """Run the full XML pipeline: request XMLs → verify/download → parse.
    Returns (ok, message). Failures are non-fatal (metadata is already saved)."""
    env = os.environ.copy()
    env["APP_DB_PATH"] = os.environ.get("APP_DB_PATH") or os.path.join(BASE_DIR, "invoicing.db")

    try:
        with decrypted_fiel_env(int(issuer_id)) as fiel_env:
            env.update(fiel_env)

            # Step 1: Request XMLs from SAT
            if os.path.isfile(PHP_SYNC_XML):
                args = [PHP_SYNC_XML, str(issuer_id), direction]
                if month:
                    args.append(f"--month={month}")
                else:
                    args.extend([f"--backfill={backfill_days}", f"--window={window_hours}"])
                args.append("--loop")
                run_php(args, cwd=SAT_SYNC_DIR, env=env, timeout=120, php_bin=PHP_BIN)

            # Step 2: Verify & download (poll up to 3 min)
            if os.path.isfile(PHP_VERIFY):
                for attempt in range(6):
                    stdout, _ = run_php(
                        [PHP_VERIFY, f"--issuer={issuer_id}"],
                        cwd=SAT_SYNC_DIR, env=env, timeout=60, php_bin=PHP_BIN,
                    )
                    if "No hay sat_requests pendientes" in (stdout or ""):
                        break
                    if "aún en proceso" not in (stdout or ""):
                        break
                    time.sleep(30)

        # Step 3: Parse downloaded XMLs (no FIEL needed)
        if os.path.isfile(PHP_PARSE_XML):
            run_php(
                [PHP_PARSE_XML, f"--issuer={issuer_id}", f"--direction={direction}", "--limit=200"],
                cwd=BASE_DIR, env=env, timeout=120, php_bin=PHP_BIN,
            )

        return True, "XML pipeline complete"
    except Exception as e:
        logger.warning("XML pipeline non-fatal error for issuer %s/%s: %s", issuer_id, direction, e)
        return False, f"{type(e).__name__}: {e}"[:300]


def _run_verify_and_parse(issuer_id: int) -> tuple[bool, str]:
    """Lightweight: just verify pending sat_requests + parse any new XMLs.
    No new SAT requests are made — only processes already-queued ones.
    Returns (ok, message)."""
    env = os.environ.copy()
    env["APP_DB_PATH"] = os.environ.get("APP_DB_PATH") or os.path.join(BASE_DIR, "invoicing.db")

    try:
        with decrypted_fiel_env(int(issuer_id)) as fiel_env:
            env.update(fiel_env)

            if not os.path.isfile(PHP_VERIFY):
                return False, "verify_requests.php not found"

            # Single pass — verify_requests.php processes up to --limit queued requests
            stdout, _ = run_php(
                [PHP_VERIFY, f"--issuer={issuer_id}", "--limit=20"],
                cwd=SAT_SYNC_DIR, env=env, timeout=120, php_bin=PHP_BIN,
            )
            out = (stdout or "").strip()
            downloaded_any = "XML guardados:" in out and "XML guardados: 0" not in out

        # Parse newly downloaded XMLs (no FIEL needed)
        if downloaded_any and os.path.isfile(PHP_PARSE_XML):
            for direction in ("issued", "received"):
                try:
                    run_php(
                        [PHP_PARSE_XML, f"--issuer={issuer_id}", f"--direction={direction}", "--limit=200"],
                        cwd=BASE_DIR, env=env, timeout=120, php_bin=PHP_BIN,
                    )
                except Exception:
                    pass  # non-fatal

        return True, out[:300]
    except Exception as e:
        logger.warning("Verify-and-parse error for issuer %s: %s", issuer_id, e)
        return False, f"{type(e).__name__}: {e}"[:300]


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
    month = payload.get("month")

    ctx.progress(10, f"Sync metadata {direction} for issuer {issuer_id}")
    ok, msg = _run_sync_php(issuer_id, direction, backfill_days=backfill, window_hours=window)
    _update_sync_state(issuer_id, direction, ok=ok, error_msg=msg if not ok else None)

    if not ok:
        raise RuntimeError(f"SAT sync failed: {msg}")

    # XML download + parse (non-fatal)
    ctx.progress(60, f"Downloading XMLs {direction}")
    _run_xml_pipeline(issuer_id, direction, backfill_days=backfill or DEFAULT_BACKFILL_DAYS, window_hours=window or DEFAULT_WINDOW_HOURS, month=month)
    ctx.progress(100, "Done")

    return {"ok": True, "message": msg}


def handle_sat_refresh_light(job: dict, ctx) -> dict:
    """Light refresh: current month issued+received for an issuer.
    Full pipeline: metadata → XML request → verify/download → parse.
    Payload: {issuer_id, directions?}
    """
    payload = job.get("payload") or {}
    issuer_id = int(payload.get("issuer_id") or job.get("issuer_id"))
    directions = payload.get("directions", ["issued", "received"])
    n = len(directions)

    results = {}
    for i, direction in enumerate(directions):
        # Step 1: Metadata
        ctx.progress(int((i / n) * 45) + 5, f"Metadata {direction}")
        ok, msg = _run_sync_php(issuer_id, direction, backfill_days=2, window_hours=6)
        _update_sync_state(issuer_id, direction, ok=ok, error_msg=msg if not ok else None)
        results[direction] = {"ok": ok, "message": msg}

    failed = [d for d, r in results.items() if not r["ok"]]
    if failed:
        raise RuntimeError(f"SAT refresh failed for: {', '.join(failed)}")

    # Step 2-3: XML download + parse (non-fatal)
    for i, direction in enumerate(directions):
        ctx.progress(55 + int((i / n) * 40), f"XMLs {direction}")
        _run_xml_pipeline(issuer_id, direction, backfill_days=2, window_hours=6)

    ctx.progress(100, "Done")
    return {"ok": True, "results": results}


def handle_sat_xml_backfill(job: dict, ctx) -> dict:
    """Retry XML download for CFDIs that have metadata but no XML.
    Payload: {issuer_id}
    Groups missing CFDIs by direction+month and runs the XML pipeline for each.
    """
    payload = job.get("payload") or {}
    issuer_id = int(payload.get("issuer_id") or job.get("issuer_id"))

    conn = db()
    try:
        rows = conn.execute(
            """SELECT direction, SUBSTR(fecha_emision, 1, 7) AS month, COUNT(*) AS cnt
               FROM sat_cfdi
               WHERE issuer_id = ?
                 AND (xml_path IS NULL OR TRIM(COALESCE(xml_path, '')) = '')
                 AND fecha_emision IS NOT NULL
               GROUP BY direction, SUBSTR(fecha_emision, 1, 7)
               ORDER BY month DESC
               LIMIT 24""",
            (issuer_id,),
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        ctx.progress(100, "No missing XMLs")
        return {"ok": True, "message": "nothing to backfill"}

    total = len(rows)
    results = []
    for i, row in enumerate(rows):
        direction = row["direction"]
        month = row["month"]
        cnt = row["cnt"]
        ctx.progress(int((i / total) * 90) + 5, f"XML backfill {direction} {month} ({cnt})")
        ok, msg = _run_xml_pipeline(issuer_id, direction, month=month)
        results.append({"direction": direction, "month": month, "ok": ok})
        logger.info("XML backfill issuer=%s %s/%s: %s", issuer_id, direction, month, msg)

    ctx.progress(100, "Done")
    return {"ok": True, "backfilled": results}


def handle_sat_verify_pending(job: dict, ctx) -> dict:
    """Verify pending SAT requests and download ready XML packages.
    Lightweight — no new SAT requests, just checks already-queued ones.
    Payload: {issuer_id}
    """
    payload = job.get("payload") or {}
    issuer_id = int(payload.get("issuer_id") or job.get("issuer_id"))

    ctx.progress(10, f"Verifying pending SAT requests for issuer {issuer_id}")
    ok, msg = _run_verify_and_parse(issuer_id)

    if not ok:
        raise RuntimeError(f"Verify pending failed: {msg}")

    ctx.progress(100, "Done")
    return {"ok": True, "message": msg}


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
