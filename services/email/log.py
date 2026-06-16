"""CRUD helpers for email_log table."""
import json
from datetime import datetime, timezone
from typing import Optional


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

from database import db


def insert_log(
    *,
    email_type: str,
    to_email: str,
    issuer_id: Optional[int] = None,
    user_id: Optional[int] = None,
    related_object_type: Optional[str] = None,
    related_object_id: Optional[int] = None,
    to_name: Optional[str] = None,
    from_email: Optional[str] = None,
    from_name: Optional[str] = None,
    reply_to: Optional[str] = None,
    subject: Optional[str] = None,
    template: Optional[str] = None,
    provider: Optional[str] = None,
    payload_context: Optional[dict] = None,
    status: str = "queued",
) -> int:
    """Insert a new email_log row and return its id."""
    conn = db()
    cur = conn.execute(
        """INSERT INTO email_log (
              issuer_id, user_id, email_type, related_object_type, related_object_id,
              to_email, to_name, from_email, from_name, reply_to,
              subject, template, provider, payload_json, status
           ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            issuer_id, user_id, email_type, related_object_type, related_object_id,
            to_email, to_name, from_email, from_name, reply_to,
            subject, template, provider,
            json.dumps(payload_context or {}, default=str),
            status,
        ),
    )
    conn.commit()
    log_id = cur.lastrowid
    conn.close()
    return log_id


def mark_sent(log_id: int, provider_message_id: Optional[str] = None) -> None:
    """Mark an email_log entry as sent."""
    conn = db()
    conn.execute(
        """UPDATE email_log
              SET status = 'sent',
                  provider_message_id = COALESCE(?, provider_message_id),
                  sent_at = ?,
                  updated_at = ?
            WHERE id = ?""",
        (provider_message_id, _now_iso(), _now_iso(), log_id),
    )
    conn.commit()
    conn.close()


def mark_failed(log_id: int, error_message: str) -> None:
    """Mark an email_log entry as failed."""
    conn = db()
    conn.execute(
        """UPDATE email_log
              SET status = 'failed',
                  error_message = ?,
                  failed_at = ?,
                  updated_at = ?
            WHERE id = ?""",
        (error_message[:500], _now_iso(), _now_iso(), log_id),
    )
    conn.commit()
    conn.close()


def update_status_by_provider_id(
    provider_message_id: str,
    new_status: str,
    timestamp_field: Optional[str] = None,
) -> int:
    """Update email_log entry when a webhook event arrives.

    Returns number of affected rows.
    """
    conn = db()
    if timestamp_field in ("delivered_at", "opened_at", "clicked_at", "bounced_at"):
        cur = conn.execute(
            f"""UPDATE email_log
                   SET status = ?,
                       {timestamp_field} = ?,
                       updated_at = ?
                 WHERE provider_message_id = ?""",
            (new_status, _now_iso(), _now_iso(), provider_message_id),
        )
    else:
        cur = conn.execute(
            """UPDATE email_log
                  SET status = ?, updated_at = ?
                WHERE provider_message_id = ?""",
            (new_status, _now_iso(), provider_message_id),
        )
    conn.commit()
    affected = cur.rowcount
    conn.close()
    return affected
