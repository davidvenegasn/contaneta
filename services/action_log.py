"""Log de acciones clave para SRE and audit trail persistente.

Dual output: Python logger (for SRE/monitoring) + audit_log table (via services/audit.py).
"""
import json
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


def log_action(request: Optional[Any], action: str, **kwargs: Any) -> None:
    """Write an action log line and persist to audit_log table.

    The request_id is added by the LogRecordFactory (middleware).
    Usage: log_action(request, "login", user_id=1, issuer_id=2)
    """
    # 1. Always log to Python logger (SRE)
    parts = [f"action={action}"]
    for k, v in sorted(kwargs.items()):
        if v is not None and v != "":
            parts.append(f"{k}={v}")
    logger.info(" ".join(parts))

    # 2. Persist to audit_log table (best-effort, never break caller)
    try:
        _persist_action(request, action, kwargs)
    except Exception:
        # DB not ready or other issue — silently skip
        pass


def _persist_action(request: Optional[Any], action: str, kwargs: dict) -> None:
    """Insert a row into the audit_log table via services/audit.py."""
    from services.audit import log as audit_log

    # Extract known fields, rest goes into meta
    issuer_id = kwargs.get("issuer_id")
    user_id = kwargs.get("user_id")
    entity_id = kwargs.get("entity_id")

    # Try to get from request.state if not in kwargs
    if request is not None:
        if issuer_id is None:
            issuer_id = getattr(getattr(request, "state", None), "issuer_id", None)
        if user_id is None:
            user_id = getattr(getattr(request, "state", None), "user_id", None)

    # Build meta from remaining kwargs (excluding known fields)
    meta_keys = {k: v for k, v in kwargs.items()
                 if k not in ("issuer_id", "user_id", "entity_id") and v is not None and v != ""}

    audit_log(
        action=action,
        user_id=int(user_id) if user_id else None,
        issuer_id=int(issuer_id) if issuer_id else None,
        entity_id=str(entity_id) if entity_id else None,
        meta=meta_keys if meta_keys else None,
        request=request,
    )


def get_audit_log(
    issuer_id: int,
    *,
    action: Optional[str] = None,
    user_id: Optional[int] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict], int]:
    """Query audit_log entries for a given issuer with optional filters.

    Returns (rows, total_count).
    """
    from database import db

    conditions = ["issuer_id = ?"]
    params: list[Any] = [issuer_id]

    if action:
        conditions.append("action = ?")
        params.append(action)
    if user_id:
        conditions.append("user_id = ?")
        params.append(user_id)
    if date_from:
        conditions.append("created_at >= ?")
        params.append(date_from)
    if date_to:
        conditions.append("created_at < date(?, '+1 day')")
        params.append(date_to)

    where = " AND ".join(conditions)

    conn = db()
    try:
        total_row = conn.execute(
            f"SELECT COUNT(*) AS cnt FROM audit_log WHERE {where}", params
        ).fetchone()
        total = total_row["cnt"] if total_row else 0

        rows = conn.execute(
            f"""SELECT al.id, al.issuer_id, al.user_id, al.action,
                       al.details, al.meta_json, al.ip, al.created_at,
                       al.entity, al.entity_id,
                       u.email AS user_email
                FROM audit_log al
                LEFT JOIN users u ON u.id = al.user_id
                WHERE {where}
                ORDER BY al.created_at DESC
                LIMIT ? OFFSET ?""",
            params + [limit, offset],
        ).fetchall()
        return [dict(r) for r in rows], total
    finally:
        conn.close()


def get_distinct_actions(issuer_id: int) -> list[str]:
    """Return distinct action types for an issuer (for filter chips)."""
    from database import db

    conn = db()
    try:
        rows = conn.execute(
            "SELECT DISTINCT action FROM audit_log WHERE issuer_id = ? ORDER BY action",
            (issuer_id,),
        ).fetchall()
        return [r["action"] for r in rows]
    finally:
        conn.close()
