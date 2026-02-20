"""Registro de auditoría para acciones sensibles (impersonación, login, descargas, etc.)."""
import json
from typing import Any, Optional

from database import db


def log(
    action: str,
    user_id: Optional[int] = None,
    issuer_id: Optional[int] = None,
    target_issuer_id: Optional[int] = None,
    details: Optional[str] = None,
    request: Optional[Any] = None,
    entity: Optional[str] = None,
    entity_id: Optional[str] = None,
    meta: Optional[dict] = None,
    ip: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> None:
    """Inserta una fila en audit_log. user_id = actor (quien hace la acción)."""
    if request is not None and ip is None:
        raw = (getattr(request, "headers", None) or {}).get("x-forwarded-for") or (
            getattr(request, "headers", None) or {}
        ).get("x-real-ip")
        if not raw and getattr(request, "client", None):
            raw = getattr(request.client, "host", None)
        ip = (raw or "").split(",")[0].strip() or None
    if request is not None and user_agent is None:
        user_agent = (getattr(request, "headers", None) or {}).get("user-agent")
    meta_json = json.dumps(meta) if meta is not None else None
    conn = db()
    try:
        conn.execute(
            """INSERT INTO audit_log (
                   action, user_id, issuer_id, target_issuer_id, details,
                   entity, entity_id, meta_json, ip, user_agent
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                action,
                user_id,
                issuer_id,
                target_issuer_id,
                details,
                entity,
                entity_id,
                meta_json,
                ip,
                user_agent,
            ),
        )
        conn.commit()
    finally:
        conn.close()
