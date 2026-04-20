from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Optional

from database import db, db_rows, has_column, table_exists
from services.month_close import pdf_exists


SEVERITY_INFO = "info"
SEVERITY_WARNING = "warning"
SEVERITY_DANGER = "danger"


def _dedupe_key(*parts: str) -> str:
    raw = "|".join([p or "" for p in parts])[:5000]
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def ensure_notifications_table() -> None:
    conn = db()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS notifications (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              issuer_id INTEGER NOT NULL,
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
        conn.commit()
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


def list_notifications(issuer_id: int, *, unread_only: bool = True, limit: int = 10) -> list[dict[str, Any]]:
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


def mark_read(issuer_id: int, notification_id: int) -> bool:
    ensure_notifications_table()
    conn = db()
    try:
        row = conn.execute(
            "SELECT id FROM notifications WHERE id = ? AND issuer_id = ? LIMIT 1",
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

    # 2) SAT sync falló (últimas 24h)
    try:
        r = db_rows(
            """
            SELECT finished_at, last_error FROM sat_jobs
            WHERE issuer_id = ? AND status = 'error' AND finished_at IS NOT NULL
              AND datetime(finished_at) >= datetime('now','-1 day')
            ORDER BY datetime(finished_at) DESC
            LIMIT 1
            """,
            (issuer_id,),
        )
        if r:
            last = r[0]
            create_notification_if_missing(
                issuer_id=issuer_id,
                type="sat_sync_failed",
                title="Falló la sincronización SAT",
                body=(last.get("last_error") or "Hubo un error al sincronizar con el SAT. Intenta de nuevo más tarde.")[:280],
                severity=SEVERITY_DANGER,
                action_url="/portal/home",
                dedupe_parts=["sat_sync_failed", (last.get("finished_at") or "")[:16]],
            )
    except Exception:
        pass

    # 3) CFDI cancelado recientemente (proxy por fecha_emision)
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

    # 4) Gastos bancarios sin CFDI (requiere_cfdi=1 y sin match probable)
    try:
        conn = db()
        if table_exists(conn, "bank_movements") and has_column(conn, "bank_movements", "period_month"):
            has_req = has_column(conn, "bank_movements", "requires_cfdi")
            has_bim = table_exists(conn, "bank_invoice_matches")
            where = ["issuer_id = ?", "period_month = ?", "COALESCE(retiro,0) >= 0.01", "COALESCE(categoria,'') != 'CUENTA_PROPIA'"]
            params = [issuer_id, ym]
            if has_req:
                where.append("COALESCE(requires_cfdi,0) = 1")
            if has_bim:
                where.append(
                    """NOT EXISTS (
                         SELECT 1 FROM bank_invoice_matches bim
                         WHERE bim.issuer_id = bank_movements.issuer_id
                           AND bim.bank_movement_id = bank_movements.id
                           AND bim.status IN ('suggested','confirmed')
                           AND COALESCE(bim.score,0) >= 80
                       )"""
                )
            row = conn.execute(f"SELECT COUNT(*) AS c FROM bank_movements WHERE {' AND '.join(where)}", tuple(params)).fetchone()
            n = int(row["c"]) if row else 0
            if n > 0:
                create_notification_if_missing(
                    issuer_id=issuer_id,
                    type="bank_expense_without_cfdi",
                    title="Gastos en banco sin factura",
                    body=f"Hay {n} movimiento(s) de gasto sin match probable a CFDI este mes.",
                    severity=SEVERITY_WARNING,
                    action_url=f"/portal/bank/movements?ym={ym}&tipo=GASTO&match_filter=none",
                    dedupe_parts=["bank_expense_without_cfdi", ym, str(n)],
                )
    except Exception:
        pass
    finally:
        try:
            conn.close()
        except Exception:
            pass

    # 5) Mes sin acuse/opinión (mes anterior)
    try:
        from datetime import timedelta

        prev = (now.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
        if not pdf_exists(issuer_id=issuer_id, ym=prev, kind="acuse"):
            create_notification_if_missing(
                issuer_id=issuer_id,
                type="month_close_missing_acuse",
                title=f"Falta acuse de {prev}",
                body="Sube el acuse de declaración para cerrar el mes.",
                severity=SEVERITY_INFO,
                action_url=f"/portal/month-close?ym={prev}",
                dedupe_parts=["month_close_missing_acuse", prev],
            )
        if not pdf_exists(issuer_id=issuer_id, ym=prev, kind="opinion"):
            create_notification_if_missing(
                issuer_id=issuer_id,
                type="month_close_missing_opinion",
                title=f"Falta opinión de {prev}",
                body="Sube la opinión de cumplimiento para cerrar el mes.",
                severity=SEVERITY_INFO,
                action_url=f"/portal/month-close?ym={prev}",
                dedupe_parts=["month_close_missing_opinion", prev],
            )
    except Exception:
        pass

