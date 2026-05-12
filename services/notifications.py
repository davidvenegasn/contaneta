"""In-app notification service — create, list, mark-read, count unread.

The notifications table is created by migration 027 and extended by 030 (meta_json)
and 050 (user_id). The ensure_notifications_table() fallback guarantees the table
exists even if migrations have not run yet (e.g. fresh dev environments).
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from database import db, db_rows, db_execute, has_column, table_exists

SEVERITY_INFO = "info"
SEVERITY_WARNING = "warning"
SEVERITY_DANGER = "danger"


def _dedupe_key(*parts: str) -> str:
    """Build a SHA-256 dedupe key from arbitrary string parts."""
    raw = "|".join([p or "" for p in parts])[:5000]
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def ensure_notifications_table() -> None:
    """Create the notifications table and indexes if they do not exist."""
    conn = db()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS notifications (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              issuer_id INTEGER NOT NULL,
              user_id INTEGER,
              type TEXT NOT NULL,
              title TEXT NOT NULL,
              body TEXT NOT NULL,
              severity TEXT NOT NULL DEFAULT 'info',
              action_url TEXT,
              dedupe_key TEXT NOT NULL,
              created_at TEXT NOT NULL DEFAULT (datetime('now')),
              read_at TEXT
            );
            """
        )
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_notifications_dedupe ON notifications(issuer_id, dedupe_key);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_notifications_issuer_read ON notifications(issuer_id, read_at, created_at);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_notif_user ON notifications(issuer_id, user_id, read_at);")
        conn.commit()
    finally:
        conn.close()


# ── Public API ────────────────────────────────────────────────────────────────


def create_notification(
    issuer_id: int,
    title: str,
    message: str = "",
    type: str = "info",
    link: str | None = None,
    user_id: int | None = None,
) -> int | None:
    """Create a new notification and return its id.  No deduplication.

    Args:
        issuer_id: Tenant ID (required).
        title: Short notification title.
        message: Longer body text (optional).
        type: Notification type/category, also used as severity. Defaults to 'info'.
        link: Optional URL the notification should navigate to.
        user_id: Optional — target a specific user within the tenant.

    Returns:
        The new notification id, or None on failure.
    """
    ensure_notifications_table()
    issuer_id = int(issuer_id)
    title = (title or "").strip()
    message = (message or "").strip()
    type = (type or SEVERITY_INFO).strip()
    if not title:
        return None

    # Map type to a valid severity for display
    severity = type if type in (SEVERITY_INFO, SEVERITY_WARNING, SEVERITY_DANGER) else SEVERITY_INFO

    conn = db()
    try:
        cur = conn.execute(
            """
            INSERT INTO notifications (issuer_id, user_id, type, title, body, severity, action_url, dedupe_key, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            """,
            (
                issuer_id,
                int(user_id) if user_id else None,
                type,
                title,
                message,
                severity,
                (link or "").strip() or None,
                _dedupe_key(str(issuer_id), str(user_id or ""), type, title, message, str(datetime.now(timezone.utc).isoformat())),
            ),
        )
        conn.commit()
        return cur.lastrowid
    except Exception:
        return None
    finally:
        conn.close()


def create_notification_if_missing(
    *,
    issuer_id: int,
    type: str,
    title: str,
    body: str,
    severity: str = SEVERITY_INFO,
    action_url: str = "",
    dedupe_parts: list[str] | None = None,
    meta: dict | None = None,
) -> bool:
    """Create a notification only if a matching dedupe_key does not exist yet.

    Returns True if a new notification was created, False if it was a duplicate.
    """
    ensure_notifications_table()
    issuer_id = int(issuer_id)
    type = (type or "").strip()
    title = (title or "").strip()
    body = (body or "").strip()
    severity = (severity or SEVERITY_INFO).strip()
    if not type or not title:
        return False
    dk = _dedupe_key(*(dedupe_parts or [type, title, body, action_url]))
    meta_json = json.dumps(meta, ensure_ascii=False) if meta else None
    conn = db()
    try:
        row = conn.execute(
            "SELECT id FROM notifications WHERE issuer_id = ? AND dedupe_key = ? LIMIT 1",
            (issuer_id, dk),
        ).fetchone()
        if row:
            return False
        try:
            conn.execute(
                """
                INSERT INTO notifications (issuer_id, type, title, body, severity, action_url, dedupe_key, meta_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                """,
                (issuer_id, type, title, body, severity, (action_url or "").strip() or None, dk, meta_json),
            )
        except Exception:
            # Fallback without meta_json if column doesn't exist yet
            conn.execute(
                """
                INSERT INTO notifications (issuer_id, type, title, body, severity, action_url, dedupe_key, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
                """,
                (issuer_id, type, title, body, severity, (action_url or "").strip() or None, dk),
            )
        conn.commit()
        return True
    finally:
        conn.close()


def get_notifications(issuer_id: int, limit: int = 20, unread_only: bool = False) -> list[dict[str, Any]]:
    """Return recent notifications for a tenant, newest first.

    Args:
        issuer_id: Tenant ID.
        limit: Maximum number of notifications to return (1-50).
        unread_only: If True, only return unread notifications.

    Returns:
        List of notification dicts.
    """
    ensure_notifications_table()
    issuer_id = int(issuer_id)
    limit = max(1, min(int(limit), 50))
    where = ["issuer_id = ?"]
    params: list[Any] = [issuer_id]
    if unread_only:
        where.append("read_at IS NULL")
    sql = f"""
      SELECT id, type, title, body, severity, action_url, created_at, read_at
      FROM notifications
      WHERE {' AND '.join(where)}
      ORDER BY datetime(created_at) DESC, id DESC
      LIMIT ?
    """
    rows = db_rows(sql, tuple(params) + (limit,))
    return rows or []


def list_notifications(issuer_id: int, *, unread_only: bool = True, limit: int = 10) -> list[dict[str, Any]]:
    """Legacy wrapper kept for backward compatibility with dashboard and operations router."""
    return get_notifications(issuer_id, limit=limit, unread_only=unread_only)


def mark_read(issuer_id: int, notification_id: int) -> bool:
    """Mark a single notification as read. Returns True if it existed and was updated.

    Args:
        issuer_id: Tenant ID (ensures tenant isolation).
        notification_id: The notification row id.

    Returns:
        True if the notification was found and marked, False otherwise.
    """
    ensure_notifications_table()
    conn = db()
    try:
        row = conn.execute(
            "SELECT id FROM notifications WHERE id = ? AND issuer_id = ? AND read_at IS NULL LIMIT 1",
            (int(notification_id), int(issuer_id)),
        ).fetchone()
        if not row:
            return False
        conn.execute(
            "UPDATE notifications SET read_at = datetime('now') WHERE id = ? AND issuer_id = ?",
            (int(notification_id), int(issuer_id)),
        )
        conn.commit()
        return True
    finally:
        conn.close()


def mark_all_read(issuer_id: int) -> int:
    """Mark all unread notifications for a tenant as read. Returns count of updated rows.

    Args:
        issuer_id: Tenant ID.

    Returns:
        Number of notifications that were marked as read.
    """
    ensure_notifications_table()
    conn = db()
    try:
        cur = conn.execute(
            "UPDATE notifications SET read_at = datetime('now') WHERE issuer_id = ? AND read_at IS NULL",
            (int(issuer_id),),
        )
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def count_unread(issuer_id: int) -> int:
    """Return the number of unread notifications for a tenant.

    Args:
        issuer_id: Tenant ID.

    Returns:
        Integer count of unread notifications.
    """
    ensure_notifications_table()
    rows = db_rows(
        "SELECT COUNT(*) AS n FROM notifications WHERE issuer_id = ? AND read_at IS NULL",
        (int(issuer_id),),
    )
    return int(rows[0]["n"]) if rows else 0


def refresh_for_issuer(issuer_id: int) -> None:
    """
    Genera notificaciones idempotentes (dedupe_key) para el Home.
    MVP: reglas simples y baratas; no corre jobs.
    """
    issuer_id = int(issuer_id)
    now = datetime.now(timezone.utc)
    ym = now.strftime("%Y-%m")

    # 0) FIEL not configured — encourage setup
    try:
        fiel_row = db_rows(
            "SELECT validation_ok FROM sat_credentials WHERE issuer_id = ? LIMIT 1",
            (issuer_id,),
        )
        if not fiel_row:
            create_notification_if_missing(
                issuer_id=issuer_id,
                type="fiel_not_configured",
                title="Conecta tu FIEL",
                body="Sube tus credenciales SAT para sincronizar facturas automáticamente.",
                severity=SEVERITY_INFO,
                action_url="/portal/config/sat",
                dedupe_parts=["fiel_not_configured"],
            )
        elif fiel_row and not fiel_row[0].get("validation_ok"):
            create_notification_if_missing(
                issuer_id=issuer_id,
                type="fiel_validation_pending",
                title="Valida tu FIEL",
                body="Tus credenciales SAT están cargadas pero no han sido validadas.",
                severity=SEVERITY_WARNING,
                action_url="/portal/config/sat",
                dedupe_parts=["fiel_validation_pending"],
            )
    except Exception:
        pass

    # 1) PPD sin complemento (aprox): usar invoices table si existe
    try:
        conn = db()
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(invoices)").fetchall()} if table_exists(conn, "invoices") else set()
        if cols and "payment_method" in cols:
            where = ["issuer_id = ?", "uuid IS NOT NULL", "payment_method = 'PPD'"]
            params: list[Any] = [issuer_id]
            if "status" in cols:
                where.append("COALESCE(status,'') != 'canceled'")
            if "cancelled" in cols:
                where.append("COALESCE(cancelled,0) = 0")
            row = conn.execute(f"SELECT COUNT(*) AS c FROM invoices WHERE {' AND '.join(where)}", tuple(params)).fetchone()
            n = int(row["c"]) if row else 0
            if n > 0:
                create_notification_if_missing(
                    issuer_id=issuer_id,
                    type="ppd_pending",
                    title="PPD pendientes",
                    body=f"Tienes {n} factura(s) PPD. Revisa si falta complemento de pago.",
                    severity=SEVERITY_WARNING,
                    action_url="/portal/facturas?tab=ppd",
                    dedupe_parts=["ppd_pending", ym, str(n)],
                )
    except Exception:
        pass
    finally:
        try:
            conn.close()
        except Exception:
            pass

    # 2) CFDI cancelado recientemente (proxy por fecha_emision)
    try:
        r = db_rows(
            """
            SELECT COUNT(*) AS n
            FROM sat_cfdi
            WHERE issuer_id = ? AND status IS NOT NULL
              AND (UPPER(TRIM(status)) IN ('C','CANCELADO','CANCELADA','0') OR UPPER(TRIM(status)) LIKE 'CANCEL%')
              AND fecha_emision IS NOT NULL
              AND date(substr(fecha_emision,1,10)) >= date('now','-7 day')
            """,
            (issuer_id,),
        )
        n = int(r[0]["n"] if r else 0)
        if n > 0:
            create_notification_if_missing(
                issuer_id=issuer_id,
                type="cfdi_cancelled_recent",
                title="CFDI cancelados recientemente",
                body=f"Detectamos {n} CFDI cancelado(s) en los últimos 7 días (según fecha de emisión).",
                severity=SEVERITY_WARNING,
                action_url="/portal/facturas?tab=received",
                dedupe_parts=["cfdi_cancelled_recent", ym, str(n)],
            )
    except Exception:
        pass

    # 3) CFDIs recibidos en las últimas 24h — una notificación por UUID
    try:
        rows = db_rows(
            """
            SELECT uuid, nombre_emisor, rfc_emisor, total, moneda, fecha_emision, serie, folio
            FROM sat_cfdi
            WHERE issuer_id = ?
              AND direction = 'received'
              AND uuid IS NOT NULL
              AND fecha_emision IS NOT NULL
              AND datetime(substr(fecha_emision, 1, 19)) >= datetime('now', '-1 day')
              AND (
                    status IS NULL
                    OR (UPPER(TRIM(status)) NOT IN ('C','CANCELADO','CANCELADA','0')
                        AND UPPER(TRIM(status)) NOT LIKE 'CANCEL%')
                  )
            ORDER BY datetime(substr(fecha_emision, 1, 19)) DESC
            LIMIT 50
            """,
            (issuer_id,),
        )
        for r in rows or []:
            emisor = (r.get("nombre_emisor") or r.get("rfc_emisor") or "Proveedor").strip()
            total = float(r.get("total") or 0)
            moneda = (r.get("moneda") or "MXN").strip()
            folio_part = ""
            if r.get("folio"):
                serie = (r.get("serie") or "").strip()
                folio_part = f" · {serie}{r.get('folio')}" if serie else f" · {r.get('folio')}"
            body = f"{emisor} — ${total:,.2f} {moneda}{folio_part}"
            create_notification_if_missing(
                issuer_id=issuer_id,
                type="cfdi_received",
                title="Nueva factura recibida",
                body=body[:280],
                severity=SEVERITY_INFO,
                action_url="/portal/facturas?tab=received",
                dedupe_parts=["cfdi_received", r.get("uuid") or ""],
            )
    except Exception:
        pass


