from __future__ import annotations

from typing import Any, Optional

from database import db, table_exists


def _ensure_table(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS error_events (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          created_at TEXT NOT NULL DEFAULT (datetime('now')),
          request_id TEXT,
          status_code INTEGER,
          error_code TEXT,
          message TEXT,
          path TEXT,
          method TEXT,
          issuer_id INTEGER,
          user_id INTEGER
        );
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_error_events_created ON error_events(created_at);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_error_events_req ON error_events(request_id);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_error_events_issuer ON error_events(issuer_id, created_at);")


def log_error_event(
    *,
    request: Optional[Any],
    status_code: int,
    error_code: str | None,
    message: str | None,
) -> None:
    """
    Guarda eventos de error (principalmente 5xx) para debug rápido.
    Regla: NO guardar secretos (body, headers, stack, tokens, etc).
    """
    try:
        rid = getattr(getattr(request, "state", None), "request_id", None) if request is not None else None
        path = (getattr(getattr(request, "url", None), "path", None) or "") if request is not None else ""
        method = (getattr(request, "method", None) or "") if request is not None else ""
        issuer_id = getattr(getattr(request, "state", None), "issuer_id", None) if request is not None else None
        user_id = getattr(getattr(request, "state", None), "user_id", None) if request is not None else None
        msg = (message or "").strip() or None
        code = (error_code or "").strip() or None

        conn = db()
        try:
            _ensure_table(conn)
            conn.execute(
                """
                INSERT INTO error_events (request_id, status_code, error_code, message, path, method, issuer_id, user_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    (rid or "")[:64] if rid else None,
                    int(status_code),
                    code[:80] if code else None,
                    msg[:500] if msg else None,
                    path[:200] if path else None,
                    method[:20] if method else None,
                    int(issuer_id) if issuer_id is not None else None,
                    int(user_id) if user_id is not None else None,
                ),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception:
        # Nunca bloquear la respuesta por fallo en logging
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
                SELECT id, created_at, request_id, status_code, error_code, message, path, method, issuer_id, user_id
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
                SELECT id, created_at, request_id, status_code, error_code, message, path, method, issuer_id, user_id
                FROM error_events
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(r) if isinstance(r, dict) else dict(r) for r in rows]
    finally:
        conn.close()

