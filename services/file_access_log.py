from __future__ import annotations

from typing import Any, Optional

from database import db


def _ensure_table(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS file_access_log (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          request_id TEXT,
          issuer_id INTEGER,
          user_id INTEGER,
          action TEXT NOT NULL,
          file_path TEXT,
          entity TEXT,
          entity_id TEXT,
          created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_file_access_log_created ON file_access_log(created_at);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_file_access_log_issuer ON file_access_log(issuer_id, created_at);")


def log_file_access(
    *,
    request: Optional[Any],
    action: str,
    issuer_id: int | None,
    user_id: int | None,
    file_path: str | None = None,
    entity: str | None = None,
    entity_id: str | None = None,
) -> None:
    """
    Log mínimo en DB para accesos a archivos (descargas/generación/exports).
    No debe guardar secretos. `file_path` idealmente relativo a storage o solo basename.
    """
    rid = getattr(getattr(request, "state", None), "request_id", None) if request is not None else None
    conn = db()
    try:
        _ensure_table(conn)
        conn.execute(
            """
            INSERT INTO file_access_log (request_id, issuer_id, user_id, action, file_path, entity, entity_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                rid,
                int(issuer_id) if issuer_id is not None else None,
                int(user_id) if user_id is not None else None,
                (action or "").strip() or "file_access",
                (file_path or "")[:500] if file_path else None,
                (entity or "")[:50] if entity else None,
                (entity_id or "")[:120] if entity_id else None,
            ),
        )
        conn.commit()
    finally:
        conn.close()

