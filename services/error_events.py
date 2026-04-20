from __future__ import annotations

import re
import traceback
from typing import Any, Optional

from database import db, has_column


def _ensure_table(conn) -> None:
    """
    Tabla de observabilidad mínima para errores 5xx.
    - `message_public`: texto seguro para mostrar al usuario (o resumen).
    - `message_internal` y `traceback_text`: SOLO para admin; siempre con redacción básica.
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS error_events (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          created_at TEXT NOT NULL DEFAULT (datetime('now')),
          request_id TEXT,
          issuer_id INTEGER,
          user_id INTEGER,
          path TEXT,
          method TEXT,
          status INTEGER,
          message_public TEXT,
          message_internal TEXT,
          traceback_text TEXT
        );
        """
    )

    # Backward/forward compatible: añade columnas si faltan (instalaciones viejas).
    cols = [
        ("created_at", "TEXT"),
        ("request_id", "TEXT"),
        ("issuer_id", "INTEGER"),
        ("user_id", "INTEGER"),
        ("path", "TEXT"),
        ("method", "TEXT"),
        ("status", "INTEGER"),
        ("message_public", "TEXT"),
        ("message_internal", "TEXT"),
        ("traceback_text", "TEXT"),
    ]
    for col, typ in cols:
        try:
            if not has_column(conn, "error_events", col):
                conn.execute(f"ALTER TABLE error_events ADD COLUMN {col} {typ}")
        except Exception:
            pass

    conn.execute("CREATE INDEX IF NOT EXISTS idx_error_events_created ON error_events(created_at);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_error_events_req ON error_events(request_id);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_error_events_issuer ON error_events(issuer_id, created_at);")


_SENSITIVE_PATTERNS = [
    # token=..., password=..., secret=...
    re.compile(r"(?i)\b(token|password|secret|api_key|apikey|authorization)\b\s*=\s*([^\s&]+)"),
    # Authorization: Bearer ...
    re.compile(r"(?i)\bauthorization:\s*bearer\s+([^\s]+)"),
]


def _redact(s: str | None) -> str | None:
    if not s:
        return None
    out = str(s)
    for rx in _SENSITIVE_PATTERNS:
        if "authorization:" in rx.pattern.lower():
            out = rx.sub("authorization: Bearer <redacted>", out)
        else:
            out = rx.sub(lambda m: f"{m.group(1)}=<redacted>", out)
    return out


def _format_traceback(exc: Exception | None) -> str | None:
    if exc is None:
        return None
    try:
        txt = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        txt = (_redact(txt) or "").strip()
        if not txt:
            return None
        return txt[:12000]
    except Exception:
        return None


def log_error_event(
    *,
    request: Optional[Any],
    status: int,
    message_public: str | None,
    message_internal: str | None = None,
    exc: Exception | None = None,
) -> None:
    """
    Guarda eventos de error (principalmente 5xx) para debug rápido.
    Regla: NO guardar secretos (body, headers completos, tokens).
    """
    try:
        rid = getattr(getattr(request, "state", None), "request_id", None) if request is not None else None
        path = (getattr(getattr(request, "url", None), "path", None) or "") if request is not None else ""
        method = (getattr(request, "method", None) or "") if request is not None else ""
        issuer_id = getattr(getattr(request, "state", None), "issuer_id", None) if request is not None else None
        user_id = getattr(getattr(request, "state", None), "user_id", None) if request is not None else None

        msg_pub = (message_public or "").strip() or None
        msg_int = (message_internal or "").strip() or None
        tb = _format_traceback(exc)

        conn = db()
        try:
            _ensure_table(conn)
            conn.execute(
                """
                INSERT INTO error_events (request_id, issuer_id, user_id, path, method, status, message_public, message_internal, traceback_text)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    (rid or "")[:64] if rid else None,
                    int(issuer_id) if issuer_id is not None else None,
                    int(user_id) if user_id is not None else None,
                    path[:200] if path else None,
                    method[:20] if method else None,
                    int(status),
                    msg_pub[:500] if msg_pub else None,
                    (_redact(msg_int) or None)[:2000] if msg_int else None,
                    tb,
                ),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception:
        return


def list_error_events(limit: int = 50, issuer_id: int | None = None) -> list[dict]:
    conn = db()
    try:
        _ensure_table(conn)
        limit = int(limit or 50)
        if limit < 1:
            limit = 1
        if limit > 200:
            limit = 200
        if issuer_id is not None:
            rows = conn.execute(
                """
                SELECT id, created_at, request_id, issuer_id, user_id, path, method, status,
                       message_public, message_internal
                FROM error_events
                WHERE issuer_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (int(issuer_id), limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT id, created_at, request_id, issuer_id, user_id, path, method, status,
                       message_public, message_internal
                FROM error_events
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(r) if isinstance(r, dict) else dict(r) for r in rows]
    finally:
        conn.close()


def cleanup_old_events(max_age_days: int = 90) -> int:
    """Delete error events older than max_age_days. Returns count deleted."""
    conn = db()
    try:
        _ensure_table(conn)
        cur = conn.execute(
            "DELETE FROM error_events WHERE datetime(created_at) < datetime('now', ?)",
            (f"-{int(max_age_days)} days",),
        )
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def get_error_event(event_id: int) -> dict | None:
    conn = db()
    try:
        _ensure_table(conn)
        row = conn.execute(
            """
            SELECT id, created_at, request_id, issuer_id, user_id, path, method, status,
                   message_public, message_internal, traceback_text
            FROM error_events
            WHERE id = ?
            LIMIT 1
            """,
            (int(event_id),),
        ).fetchone()
        if not row:
            return None
        return dict(row) if isinstance(row, dict) else dict(row)
    finally:
        conn.close()

