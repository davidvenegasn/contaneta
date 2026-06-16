"""Cancellation log CRUD helpers."""
import logging
from datetime import datetime, timezone
from typing import Optional

from database import db, db_rows

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def insert_log(
    *,
    issuer_id: int,
    user_id: int,
    cfdi_uuid: str,
    motivo: str,
    event: str,
    substitute_uuid: Optional[str] = None,
    provider_response_json: Optional[str] = None,
    error_message: Optional[str] = None,
) -> int:
    """Insert a row into cancellation_log. Returns the new row id."""
    conn = db()
    try:
        cur = conn.execute(
            """INSERT INTO cancellation_log
               (issuer_id, user_id, cfdi_uuid, motivo, substitute_uuid, event,
                provider_response_json, error_message, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (issuer_id, user_id, cfdi_uuid, motivo, substitute_uuid, event,
             provider_response_json, error_message, _now_iso()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def get_logs_for_uuid(cfdi_uuid: str, issuer_id: int) -> list[dict]:
    """Return all cancellation log entries for a given CFDI UUID."""
    return db_rows(
        "SELECT * FROM cancellation_log WHERE cfdi_uuid = ? AND issuer_id = ? ORDER BY created_at DESC",
        (cfdi_uuid, issuer_id),
    )
