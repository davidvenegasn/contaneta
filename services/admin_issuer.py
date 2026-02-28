"""Metadatos de admin por issuer: notas y flag necesita revisión."""
from __future__ import annotations

from database import db, db_rows, table_exists


def get_meta(issuer_id: int) -> dict | None:
    """Devuelve admin_notes y needs_review para el issuer, o None si no hay fila."""
    if not issuer_id or issuer_id <= 0:
        return None
    conn = db()
    try:
        if not table_exists(conn, "admin_issuer_meta"):
            return None
        rows = db_rows(
            "SELECT issuer_id, admin_notes, needs_review, updated_at FROM admin_issuer_meta WHERE issuer_id = ? LIMIT 1",
            (int(issuer_id),),
        )
        if not rows:
            return {"issuer_id": issuer_id, "admin_notes": "", "needs_review": 0, "updated_at": None}
        r = rows[0]
        return {
            "issuer_id": r["issuer_id"],
            "admin_notes": (r.get("admin_notes") or "").strip(),
            "needs_review": int(r.get("needs_review") or 0),
            "updated_at": r.get("updated_at"),
        }
    finally:
        conn.close()


def update_meta(issuer_id: int, *, admin_notes: str | None = None, needs_review: bool | None = None) -> None:
    """Crea o actualiza la fila en admin_issuer_meta."""
    issuer_id = int(issuer_id)
    conn = db()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS admin_issuer_meta (
              issuer_id INTEGER PRIMARY KEY,
              admin_notes TEXT,
              needs_review INTEGER NOT NULL DEFAULT 0,
              created_at TEXT NOT NULL DEFAULT (datetime('now')),
              updated_at TEXT NOT NULL DEFAULT (datetime('now')),
              FOREIGN KEY (issuer_id) REFERENCES issuers(id) ON DELETE CASCADE
            )
            """
        )
        conn.commit()
    except Exception:
        pass
    try:
        row = conn.execute(
            "SELECT admin_notes, needs_review FROM admin_issuer_meta WHERE issuer_id = ? LIMIT 1",
            (issuer_id,),
        ).fetchone()
        row = dict(row) if row else None
    except Exception:
        row = None
    try:
        notes = admin_notes if admin_notes is not None else (row.get("admin_notes") if row else "") or ""
        need = int(needs_review) if needs_review is not None else (int(row.get("needs_review") or 0) if row else 0)
        conn.execute(
            """
            INSERT INTO admin_issuer_meta (issuer_id, admin_notes, needs_review, created_at, updated_at)
            VALUES (?, ?, ?, datetime('now'), datetime('now'))
            ON CONFLICT(issuer_id) DO UPDATE SET
              admin_notes = excluded.admin_notes,
              needs_review = excluded.needs_review,
              updated_at = datetime('now')
            """,
            (issuer_id, notes, need),
        )
        conn.commit()
    finally:
        conn.close()
