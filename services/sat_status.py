"""SAT connection status and sync history — stateless service functions."""

import logging
from datetime import datetime, timezone

from database import db, db_rows, has_column, table_exists

logger = logging.getLogger(__name__)


def get_sat_connection_status(issuer_id: int) -> dict:
    """Return SAT connection info for the given issuer.

    Args:
        issuer_id: Tenant ID.

    Returns:
        Dict with keys:
            connected (bool): True if FIEL credentials exist and were validated OK.
            fiel_expires_at (str|None): Not available from current schema (placeholder).
            fiel_days_remaining (int|None): Not available from current schema (placeholder).
            last_sync_at (str|None): Last successful sync timestamp.
            last_sync_status (str|None): 'success', 'error', or None.
            invoices_synced (int): Total synced CFDI count for this issuer.
    """
    conn = db()
    try:
        # Check FIEL credentials
        has_validation_ok = has_column(conn, "sat_credentials", "validation_ok")
        if has_validation_ok:
            cred = conn.execute(
                "SELECT issuer_id, validation_ok, validation_at, validation_message "
                "FROM sat_credentials WHERE issuer_id = ? LIMIT 1",
                (int(issuer_id),),
            ).fetchone()
        else:
            cred = conn.execute(
                "SELECT issuer_id FROM sat_credentials WHERE issuer_id = ? LIMIT 1",
                (int(issuer_id),),
            ).fetchone()

        has_fiel = cred is not None
        # Connected means has FIEL and validation passed (or no validation column yet)
        if has_fiel and has_validation_ok:
            connected = bool(cred.get("validation_ok"))
        else:
            connected = has_fiel

        # FIEL expiry: not stored in DB schema, set to None
        fiel_expires_at = None
        fiel_days_remaining = None

        # Last sync info from sat_jobs table
        last_ok = conn.execute(
            "SELECT MAX(finished_at) AS t FROM sat_jobs "
            "WHERE issuer_id = ? AND status = 'ok'",
            (int(issuer_id),),
        ).fetchone()

        last_error = conn.execute(
            "SELECT finished_at FROM sat_jobs "
            "WHERE issuer_id = ? AND status = 'error' "
            "ORDER BY finished_at DESC LIMIT 1",
            (int(issuer_id),),
        ).fetchone()

        # Also check sat_sync_state for last_run_at
        sync_state = conn.execute(
            "SELECT MAX(last_run_at) AS t FROM sat_sync_state WHERE issuer_id = ?",
            (int(issuer_id),),
        ).fetchone()

        last_sync_at = (
            (sync_state and sync_state.get("t"))
            or (last_ok and last_ok.get("t"))
            or None
        )

        # Determine last sync status
        last_ok_ts = (last_ok and last_ok.get("t")) or ""
        last_err_ts = (last_error and last_error.get("finished_at")) or ""
        if last_err_ts and (not last_ok_ts or last_err_ts > last_ok_ts):
            last_sync_status = "error"
        elif last_ok_ts:
            last_sync_status = "success"
        else:
            last_sync_status = None

        # Count synced invoices (sat_cfdi entries)
        cfdi_count = conn.execute(
            "SELECT COUNT(*) AS cnt FROM sat_cfdi WHERE issuer_id = ?",
            (int(issuer_id),),
        ).fetchone()
        invoices_synced = int(cfdi_count["cnt"]) if cfdi_count else 0

    finally:
        conn.close()

    return {
        "connected": connected,
        "fiel_expires_at": fiel_expires_at,
        "fiel_days_remaining": fiel_days_remaining,
        "last_sync_at": last_sync_at,
        "last_sync_status": last_sync_status,
        "invoices_synced": invoices_synced,
    }


def get_sync_history(issuer_id: int, limit: int = 10) -> list:
    """Return recent SAT sync attempts from sat_jobs table.

    Args:
        issuer_id: Tenant ID.
        limit: Max number of records to return (default 10).

    Returns:
        List of dicts with keys: id, job_type, direction, status,
        started_at, finished_at, last_error.
    """
    limit = max(1, min(limit, 100))
    rows = db_rows(
        "SELECT id, job_type, direction, status, started_at, finished_at, last_error "
        "FROM sat_jobs WHERE issuer_id = ? "
        "ORDER BY created_at DESC LIMIT ?",
        (int(issuer_id), limit),
    )
    return rows


def check_fiel_expiry_warning(issuer_id: int) -> dict | None:
    """Check if FIEL expires within 30 days.

    Since the current schema does not store FIEL expiry dates,
    this checks the validation status instead as a proxy.

    Args:
        issuer_id: Tenant ID.

    Returns:
        Dict with warning info if FIEL has issues, or None if all OK.
        Keys: level ('warning'|'error'), message (str), days_remaining (int|None).
    """
    conn = db()
    try:
        has_validation_ok = has_column(conn, "sat_credentials", "validation_ok")
        if not has_validation_ok:
            # Cannot check without validation columns
            cred = conn.execute(
                "SELECT issuer_id FROM sat_credentials WHERE issuer_id = ? LIMIT 1",
                (int(issuer_id),),
            ).fetchone()
            if not cred:
                return {
                    "level": "error",
                    "message": "No se han configurado credenciales FIEL.",
                    "days_remaining": None,
                }
            return None

        cred = conn.execute(
            "SELECT validation_ok, validation_at, validation_message "
            "FROM sat_credentials WHERE issuer_id = ? LIMIT 1",
            (int(issuer_id),),
        ).fetchone()

        if not cred:
            return {
                "level": "error",
                "message": "No se han configurado credenciales FIEL.",
                "days_remaining": None,
            }

        if not cred.get("validation_ok"):
            return {
                "level": "error",
                "message": cred.get("validation_message") or "La FIEL no es valida.",
                "days_remaining": None,
            }

        # FIEL is valid; no expiry date in DB to check
        return None

    finally:
        conn.close()
