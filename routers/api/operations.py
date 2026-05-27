"""Operations API routes."""
import logging
from datetime import datetime
from typing import Optional

from fastapi import Body, Depends, HTTPException, Query, Request

from database import db, db_rows, table_exists
from routers.api._helpers import (
    DEFAULT_LIST_LIMIT,
    MAX_LIST_LIMIT,
    _get_month_totals_safe,
)
from routers.deps import get_portal_issuer

logger = logging.getLogger(__name__)

try:
    from cfdi_pdf import CLAVE_UNIDAD, FORMA_PAGO, MONEDA, REGIMEN_FISCAL, USO_CFDI
except Exception:
    USO_CFDI = {"G03": "Gastos en general", "G01": "Adquisición de mercancías", "CN01": "Nómina"}
    REGIMEN_FISCAL = {"601": "General de Ley Personas Morales", "612": "Personas Físicas con Actividades Empresariales", "616": "Sin obligaciones fiscales", "626": "Régimen Simplificado de Confianza"}
    FORMA_PAGO = {"03": "Transferencia electrónica", "01": "Efectivo", "99": "Por definir"}
    MONEDA = {"MXN": "Peso Mexicano", "USD": "Dólar Americano"}
    CLAVE_UNIDAD = {"E48": "Unidad de servicio", "EA": "Cada uno", "H87": "Pieza"}

from services.action_log import log_action
from services.auth import csrf as csrf_service
from services.http import ok, ok_list


def register_operations_routes(router):
    """Register Operations routes on the API router."""

    # ---------- Global search ----------

    @router.get("/search")
    def api_global_search(request: Request, q: str = Query(""), issuer: dict = Depends(get_portal_issuer)):
        """Search across clients, providers, products, invoices, movements. Returns max 5 per category."""
        from services.tenant import require_issuer_id
        issuer_id = require_issuer_id(issuer)
        q = (q or "").strip()
        if len(q) < 2:
            return {"clientes": [], "proveedores": [], "productos": [], "facturas": [], "movimientos": []}

        from services.db_utils import escape_like
        like = f"%{escape_like(q)}%"
        limit = 5

        # Clients
        clientes = db_rows(
            """SELECT id, rfc, legal_name, alias FROM customer_profiles
               WHERE issuer_id = ? AND (legal_name LIKE ? ESCAPE '\\' OR rfc LIKE ? ESCAPE '\\' OR alias LIKE ? ESCAPE '\\')
               ORDER BY legal_name LIMIT ?""",
            (issuer_id, like, like, like, limit),
        ) or []
        clientes_out = [{"id": c["id"], "nombre": c.get("legal_name") or c.get("alias") or "", "rfc": c.get("rfc") or "", "url": f"/portal/catalogos?tab=clientes&highlight={c['id']}"} for c in clientes]

        # Providers (from received invoices — distinct emitters)
        proveedores = db_rows(
            """SELECT rfc_emisor AS rfc, nombre_emisor AS nombre, COUNT(*) AS facturas
               FROM sat_cfdi
               WHERE issuer_id = ? AND direction = 'received'
                 AND (nombre_emisor LIKE ? ESCAPE '\\' OR rfc_emisor LIKE ? ESCAPE '\\')
               GROUP BY rfc_emisor
               ORDER BY facturas DESC LIMIT ?""",
            (issuer_id, like, like, limit),
        ) or []
        proveedores_out = [{"nombre": p.get("nombre") or "", "rfc": p.get("rfc") or "", "facturas": p.get("facturas") or 0, "url": f"/portal/catalogos?tab=proveedores&q={q}"} for p in proveedores]

        # Products
        productos = db_rows(
            """SELECT id, description, product_key, unit_price FROM issuer_products
               WHERE issuer_id = ? AND (description LIKE ? ESCAPE '\\' OR product_key LIKE ? ESCAPE '\\')
               ORDER BY description LIMIT ?""",
            (issuer_id, like, like, limit),
        ) or []
        productos_out = [{"id": p["id"], "nombre": p.get("description") or "", "clave": p.get("product_key") or "", "precio": float(p["unit_price"]) if p.get("unit_price") else 0, "url": f"/portal/catalogos?tab=productos&highlight={p['id']}"} for p in productos]

        # Invoices (both issued and received)
        facturas = db_rows(
            """SELECT uuid, direction, fecha_emision, nombre_emisor, nombre_receptor, total, rfc_emisor, rfc_receptor
               FROM sat_cfdi
               WHERE issuer_id = ? AND (
                 nombre_receptor LIKE ? ESCAPE '\\' OR nombre_emisor LIKE ? ESCAPE '\\'
                 OR rfc_receptor LIKE ? ESCAPE '\\' OR rfc_emisor LIKE ? ESCAPE '\\'
                 OR uuid LIKE ? ESCAPE '\\'
               )
               ORDER BY fecha_emision DESC LIMIT ?""",
            (issuer_id, like, like, like, like, like, limit),
        ) or []
        facturas_out = []
        for f in facturas:
            dir_label = "Emitida" if f.get("direction") == "issued" else "Recibida"
            nombre = f.get("nombre_receptor") if f.get("direction") == "issued" else f.get("nombre_emisor")
            tab = "emitidas" if f.get("direction") == "issued" else "recibidas"
            facturas_out.append({
                "uuid": f.get("uuid") or "",
                "tipo": dir_label,
                "nombre": nombre or "",
                "total": float(f["total"]) if f.get("total") else 0,
                "fecha": (f.get("fecha_emision") or "")[:10],
                "url": f"/portal/facturas?tab={tab}&q={q}",
            })

        # Bank movements
        movimientos = []
        try:
            if table_exists(db(), "bank_movements"):
                movimientos = db_rows(
                    """SELECT id, fecha, concepto, monto, tipo FROM bank_movements
                       WHERE issuer_id = ? AND concepto LIKE ? ESCAPE '\\'
                       ORDER BY fecha DESC LIMIT ?""",
                    (issuer_id, like, limit),
                ) or []
        except Exception:
            pass
        movimientos_out = [{"id": m["id"], "concepto": m.get("concepto") or "", "monto": float(m["monto"]) if m.get("monto") else 0, "fecha": (m.get("fecha") or "")[:10], "tipo": m.get("tipo") or "", "url": f"/portal/movimientos?q={q}"} for m in movimientos]

        return {
            "clientes": clientes_out,
            "proveedores": proveedores_out,
            "productos": productos_out,
            "facturas": facturas_out,
            "movimientos": movimientos_out,
        }

    @router.get("/invoices/pending")
    def api_pending_invoices(
        issuer: dict = Depends(get_portal_issuer),
        limit: int = Query(DEFAULT_LIST_LIMIT, ge=1, le=MAX_LIST_LIMIT, description="Máximo de registros"),
        offset: int = Query(0, ge=0, description="Registros a saltar"),
    ):
        try:
            conn = db()
            cols = {r["name"] for r in conn.execute("PRAGMA table_info(invoices)").fetchall()}
            where = ["issuer_id = ?", "uuid IS NOT NULL", "payment_method = 'PPD'"]
            params = [issuer["id"]]
            if "status" in cols:
                where.append("COALESCE(status,'') != 'canceled'")
            if "cancelled" in cols:
                where.append("COALESCE(cancelled,0) = 0")
            where_sql = " AND ".join(where)
            count_row = conn.execute(
                f"SELECT COUNT(*) AS c FROM invoices WHERE {where_sql}",
                tuple(params),
            ).fetchone()
            total = int(count_row.get("c", 0)) if count_row else 0
            rows = conn.execute(
                f"""SELECT id, uuid, total, customer_legal_name, customer_rfc, issue_date, created_at
                    FROM invoices WHERE {where_sql}
                    ORDER BY COALESCE(issue_date, created_at) DESC LIMIT ? OFFSET ?""",
                tuple(params) + (limit, offset),
            ).fetchall()
            conn.close()
            items = [{"id": r["id"], "uuid": r["uuid"], "total": r["total"], "customer_legal_name": r["customer_legal_name"],
                      "customer_rfc": r["customer_rfc"], "date": r["issue_date"] or r["created_at"]} for r in rows]
            return {"items": items, "total": total}
        except Exception:
            logger.exception("api invoices list: issuer_id=%s", issuer.get("id"))
            raise HTTPException(
                status_code=500,
                detail="No pudimos cargar la lista. Intenta de nuevo.",
            )


    @router.get("/month-close")
    def api_month_close_get(
        request: Request,
        issuer: dict = Depends(get_portal_issuer),
        ym: str = Query(..., min_length=7, max_length=7),
    ):
        from services import month_close as mc
        issuer_id = int(issuer.get("id") or 0)
        if issuer_id <= 0:
            raise HTTPException(status_code=401, detail="Sesión inválida")
        try:
            data = mc.get_full_month_close(issuer_id, ym)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        return ok(data)


    @router.post("/month-close")
    def api_month_close_post(
        request: Request,
        issuer: dict = Depends(get_portal_issuer),
        body: dict = Body(...),
    ):
        csrf_service.verify_api_csrf(request)
        from services import month_close as mc
        issuer_id = int(issuer.get("id") or 0)
        if issuer_id <= 0:
            raise HTTPException(status_code=401, detail="Sesión inválida")
        ym = (body.get("ym") or "").strip()
        status = body.get("status")
        checklist = body.get("checklist")
        try:
            data = mc.save_month_close(issuer_id, ym, status=status, checklist=checklist)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        log_action(request, "month_close_save", issuer_id=issuer_id, ym=ym)
        return ok(data)


    # ---------- Matching Preview API ----------

    @router.get("/matching/preview")
    def api_matching_preview(
        request: Request,
        issuer: dict = Depends(get_portal_issuer),
        ym: str = Query(..., min_length=7, max_length=7),
    ):
        from services.invoices.matching import preview_month
        issuer_id = int(issuer.get("id") or 0)
        if issuer_id <= 0:
            raise HTTPException(status_code=401, detail="Sesión inválida")
        try:
            result = preview_month(issuer_id, ym)
        except Exception as e:
            logger.warning("matching preview error: %s", e)
            return ok({"ok": False, "message": str(e)})
        return ok(result)

    @router.get("/activity")
    def api_activity(
        request: Request,
        issuer: dict = Depends(get_portal_issuer),
        limit: int = Query(20, ge=1, le=100),
    ):
        """Recent CFDIs (issued + received) for the activity feed / notification drawer."""
        from datetime import date as _date
        issuer_id = int(issuer.get("id") or 0)
        if issuer_id <= 0:
            raise HTTPException(status_code=401, detail="Sesión inválida")
        if not table_exists(db(), "sat_cfdi"):
            return ok_list([], 0)
        rows = db_rows(
            """
            SELECT direction, fecha_emision, nombre, total, uuid FROM (
              SELECT direction, fecha_emision, nombre_receptor AS nombre, total, uuid FROM sat_cfdi
              WHERE issuer_id = ? AND direction = 'issued' AND fecha_emision IS NOT NULL
                AND (total IS NULL OR total >= 0.01)
              UNION ALL
              SELECT direction, fecha_emision, nombre_emisor AS nombre, total, uuid FROM sat_cfdi
              WHERE issuer_id = ? AND direction = 'received' AND fecha_emision IS NOT NULL
                AND total IS NOT NULL AND total >= 0.01
                AND (tipo_comprobante IS NULL OR UPPER(TRIM(tipo_comprobante)) != 'N')
            ) ORDER BY fecha_emision DESC LIMIT ?
            """,
            (issuer_id, issuer_id, limit),
        )
        today = _date.today()
        for a in rows:
            try:
                fd = datetime.strptime((a["fecha_emision"] or "")[:10], "%Y-%m-%d").date()
                d = (today - fd).days
                a["time_ago"] = "Hoy" if d == 0 else "Ayer" if d == 1 else f"Hace {d} días"
            except (ValueError, TypeError):
                a["time_ago"] = (a.get("fecha_emision") or "")[:10] or "-"
        return ok_list(rows, len(rows))


    # ---------- Notifications API ----------

    @router.get("/notifications")
    def api_notifications_list(
        request: Request,
        issuer: dict = Depends(get_portal_issuer),
        unread_only: bool = Query(False),
        limit: int = Query(20, ge=1, le=50),
    ):
        """List notifications for the current tenant. Includes unread_count in meta."""
        from services import notifications as notif_service
        issuer_id = int(issuer.get("id") or 0)
        if issuer_id <= 0:
            raise HTTPException(status_code=401, detail="Sesión inválida")
        items = notif_service.get_notifications(issuer_id, limit=limit, unread_only=unread_only)
        unread = notif_service.count_unread(issuer_id)
        return ok_list(items, len(items), unread_count=unread)

    @router.get("/notifications/unread-count")
    def api_notifications_unread_count(
        request: Request,
        issuer: dict = Depends(get_portal_issuer),
    ):
        """Return the count of unread notifications for the current tenant."""
        from services import notifications as notif_service
        issuer_id = int(issuer.get("id") or 0)
        if issuer_id <= 0:
            raise HTTPException(status_code=401, detail="Sesión inválida")
        return ok({"unread_count": notif_service.count_unread(issuer_id)})

    @router.post("/notifications/{notification_id}/read")
    def api_notification_mark_read(
        request: Request,
        notification_id: int,
        issuer: dict = Depends(get_portal_issuer),
    ):
        """Mark a single notification as read."""
        csrf_service.verify_api_csrf(request)
        from services import notifications as notif_service
        issuer_id = int(issuer.get("id") or 0)
        if issuer_id <= 0:
            raise HTTPException(status_code=401, detail="Sesión inválida")
        success = notif_service.mark_read(issuer_id, notification_id)
        return ok({"marked": success})

    @router.post("/notifications/read-all")
    def api_notifications_read_all(
        request: Request,
        issuer: dict = Depends(get_portal_issuer),
    ):
        """Mark all unread notifications as read (single UPDATE, no loop)."""
        csrf_service.verify_api_csrf(request)
        from services import notifications as notif_service
        issuer_id = int(issuer.get("id") or 0)
        if issuer_id <= 0:
            raise HTTPException(status_code=401, detail="Sesión inválida")
        count = notif_service.mark_all_read(issuer_id)
        return ok({"marked": count})

    @router.post("/notifications/mark-all-read")
    def api_notifications_mark_all_read(
        request: Request,
        issuer: dict = Depends(get_portal_issuer),
    ):
        """Legacy alias kept for backward compat — prefer /notifications/read-all."""
        csrf_service.verify_api_csrf(request)
        from services import notifications as notif_service
        issuer_id = int(issuer.get("id") or 0)
        if issuer_id <= 0:
            raise HTTPException(status_code=401, detail="Sesión inválida")
        count = notif_service.mark_all_read(issuer_id)
        return ok({"marked": count})


    # ── SAT Sync Status ──────────────────────────────────────────────

    @router.get("/sat/status")
    def api_sat_status(issuer: dict = Depends(get_portal_issuer)):
        """Return SAT sync status for current issuer: credentials, sync state, recent jobs."""
        issuer_id = int(issuer.get("id") or 0)
        if issuer_id <= 0:
            raise HTTPException(status_code=401, detail="Sesión inválida")

        # Credentials status
        creds = None
        try:
            rows = db_rows(
                "SELECT validation_ok, validation_at, validation_message FROM sat_credentials WHERE issuer_id = ?",
                (issuer_id,),
            )
            if rows:
                creds = {"validation_ok": bool(rows[0].get("validation_ok")), "validation_at": rows[0].get("validation_at"), "message": rows[0].get("validation_message")}
        except Exception:
            pass

        # Sync state per direction
        sync_states = {}
        try:
            for row in db_rows(
                "SELECT direction, last_success_at, last_attempt_at, last_error, cooldown_until FROM sat_sync_state WHERE issuer_id = ?",
                (issuer_id,),
            ):
                sync_states[row["direction"]] = {
                    "last_success_at": row.get("last_success_at"),
                    "last_attempt_at": row.get("last_attempt_at"),
                    "last_error": row.get("last_error"),
                    "cooldown_until": row.get("cooldown_until"),
                }
        except Exception:
            pass

        # Recent jobs (last 10)
        recent_jobs = []
        try:
            recent_jobs = db_rows(
                """SELECT id, job_type, direction, status, last_error, started_at, finished_at, created_at
                   FROM sat_jobs WHERE issuer_id = ? ORDER BY id DESC LIMIT 10""",
                (issuer_id,),
            )
        except Exception:
            pass

        # Summary flags
        has_queued = any(j.get("status") in ("queued", "running") for j in recent_jobs)

        return ok({
            "credentials": creds,
            "sync_state": sync_states,
            "recent_jobs": recent_jobs,
            "has_pending_jobs": has_queued,
        })


    # ── Manual Movements ─────────────────────────────────────────────

    @router.post("/movements/manual")
    def api_manual_movement_create(
        request: Request,
        issuer: dict = Depends(get_portal_issuer),
        body: dict = Body(...),
    ):
        """Create a manual income/expense movement."""
        csrf_service.verify_api_csrf(request)
        issuer_id = int(issuer.get("id") or 0)
        if issuer_id <= 0:
            raise HTTPException(status_code=401, detail="Sesión inválida")
        from services.invoices import manual_movements as mm
        mm.ensure_table()
        fecha = (body.get("fecha") or "").strip()
        descripcion = (body.get("descripcion") or "").strip()
        monto = body.get("monto")
        tipo = (body.get("tipo") or "").strip().upper()
        categoria = (body.get("categoria") or "").strip() or None
        notas = (body.get("notas") or "").strip() or None
        forma_pago = (body.get("forma_pago") or "").strip() or None
        contraparte = (body.get("contraparte") or "").strip() or None
        moneda = (body.get("moneda") or "MXN").strip().upper()
        if not fecha or not descripcion or not monto or not tipo:
            raise HTTPException(status_code=422, detail="fecha, descripcion, monto y tipo son requeridos")
        try:
            monto = float(monto)
        except (TypeError, ValueError):
            raise HTTPException(status_code=422, detail="monto debe ser numérico")
        if monto <= 0:
            raise HTTPException(status_code=422, detail="monto debe ser mayor a 0")
        row = mm.create(issuer_id, fecha, descripcion, monto, tipo, categoria, notas,
                        forma_pago=forma_pago, contraparte=contraparte, moneda=moneda)
        return ok(row)


    @router.get("/movements/manual")
    def api_manual_movements_list(
        request: Request,
        issuer: dict = Depends(get_portal_issuer),
        ym: Optional[str] = Query(None),
        tipo: Optional[str] = Query(None),
        limit: int = Query(200, ge=1, le=500),
        offset: int = Query(0, ge=0),
    ):
        """List manual movements for the current issuer."""
        issuer_id = int(issuer.get("id") or 0)
        if issuer_id <= 0:
            raise HTTPException(status_code=401, detail="Sesión inválida")
        from services.invoices import manual_movements as mm
        mm.ensure_table()
        items = mm.list_movements(issuer_id, period_month=ym, tipo=tipo, limit=limit, offset=offset)
        total = mm.count_movements(issuer_id, period_month=ym)
        return ok_list(items, total)


    @router.delete("/movements/manual/{movement_id}")
    def api_manual_movement_delete(movement_id: int, request: Request, issuer: dict = Depends(get_portal_issuer)):
        """Delete a manual movement."""
        csrf_service.verify_api_csrf(request)
        issuer_id = int(issuer.get("id") or 0)
        if issuer_id <= 0:
            raise HTTPException(status_code=401, detail="Sesión inválida")
        from services.invoices import manual_movements as mm
        mm.ensure_table()
        deleted = mm.delete(issuer_id, movement_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Movimiento no encontrado")
        return ok({"deleted": True})


    # ── Foreign Invoices ─────────────────────────────────────────────

    @router.get("/exchange-rate")
    def api_exchange_rate(
        request: Request,
        issuer: dict = Depends(get_portal_issuer),
        moneda: str = Query("USD"),
        period: str = Query(None),
    ):
        """Get exchange rate for a currency+month."""
        from services.invoices.exchange_rates import get_rate
        if not period:
            period = datetime.now().strftime("%Y-%m")
        rate = get_rate(moneda, period)
        return ok({"moneda": moneda.upper(), "period": period, "rate": rate})


    @router.get("/exchange-rates")
    def api_exchange_rates_list(
        request: Request,
        issuer: dict = Depends(get_portal_issuer),
        moneda: str = Query(None),
    ):
        """List exchange rates."""
        from services.invoices.exchange_rates import list_rates
        rates = list_rates(moneda=moneda)
        return ok_list(rates, len(rates))


    @router.post("/exchange-rates")
    def api_exchange_rate_set(
        request: Request,
        issuer: dict = Depends(get_portal_issuer),
        body: dict = Body(...),
    ):
        """Set an exchange rate for a currency+month."""
        csrf_service.verify_api_csrf(request)
        from services.invoices.exchange_rates import set_rate
        moneda = (body.get("moneda") or "").strip().upper()
        period = (body.get("period") or "").strip()
        rate = body.get("rate")
        if not moneda or not period or not rate:
            raise HTTPException(status_code=422, detail="moneda, period, rate requeridos")
        try:
            rate = float(rate)
        except (TypeError, ValueError):
            raise HTTPException(status_code=422, detail="rate debe ser numérico")
        if rate <= 0:
            raise HTTPException(status_code=422, detail="rate debe ser mayor a 0")
        set_rate(moneda, period, rate, source="user")
        return ok({"moneda": moneda, "period": period, "rate": rate})



    @router.get("/metrics/trend")
    def api_metrics_trend(
        request: Request,
        issuer: dict = Depends(get_portal_issuer),
        months: int = Query(12, ge=1, le=24),
    ):
        """Return monthly totals for issued/received over the last N months (for sparklines and charts).
        Smart: if user has less than N months of data, show only from first month with data."""
        issuer_id = int(issuer.get("id") or 0)
        if issuer_id <= 0:
            raise HTTPException(status_code=401, detail="Sesión inválida")
        from datetime import date
        today = date.today()

        # Smart range: detect first month with data
        try:
            conn = db()
            row = conn.execute(
                "SELECT MIN(substr(fecha_emision,1,7)) AS first_ym FROM sat_cfdi WHERE issuer_id = ? AND fecha_emision IS NOT NULL",
                (issuer_id,),
            ).fetchone()
            conn.close()
            first_ym = (row["first_ym"] or "") if row else ""
        except Exception:
            first_ym = ""

        if first_ym and len(first_ym) == 7:
            try:
                fy, fm = int(first_ym[:4]), int(first_ym[5:7])
                months_with_data = (today.year - fy) * 12 + (today.month - fm) + 1
                months = min(months, max(1, months_with_data))
            except (ValueError, TypeError):
                pass

        result = []
        y, m = today.year, today.month
        # Build list of last N months (inclusive of current)
        ym_list = []
        for _ in range(months):
            ym_list.append(f"{y:04d}-{m:02d}")
            m -= 1
            if m <= 0:
                m = 12
                y -= 1
        ym_list.reverse()
        for ym in ym_list:
            tot_issued = _get_month_totals_safe(issuer_id, ym, "issued")
            tot_received = _get_month_totals_safe(issuer_id, ym, "received")
            result.append({
                "ym": ym,
                "ingresos": tot_issued.get("total_base", 0),
                "gastos": tot_received.get("total_base", 0),
                "iva_cobrado": tot_issued.get("total_iva_neto", 0),
                "iva_pagado": tot_received.get("total_iva", 0),
            })
        return ok(result)

