# Portal HTML routes and helpers
import os
from datetime import datetime, date
from typing import Optional

from fastapi import APIRouter, Request, Depends, Query, HTTPException
from fastapi.responses import HTMLResponse, Response, RedirectResponse

from config import BASE_DIR, REGIMEN_LABEL_TO_CODE, COOKIE_DEMO_VIEW
from database import db, db_rows, has_column
from routers.deps import get_portal_issuer
from services import quotations as quotations_service, session as session_service, audit, subscription as subscription_service, csrf as csrf_service

# ----------------------------
# Helpers
# ----------------------------

MESES_ES = (
    "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
    "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"
)


def ym_now():
    return datetime.now().strftime("%Y-%m")


def ym_to_label(ym: str) -> str:
    """Convert 2026-01 to 'Enero 2026'."""
    try:
        y, m = ym.split("-")
        return f"{MESES_ES[int(m) - 1]} {y}"
    except (ValueError, IndexError):
        return ym


def shift_ym(ym: str, delta_months: int) -> str:
    y, m = ym.split("-")
    y, m = int(y), int(m)
    m += delta_months
    while m <= 0:
        m += 12
        y -= 1
    while m >= 13:
        m -= 12
        y += 1
    return f"{y:04d}-{m:02d}"


def _get_month_totals(issuer_id: int, ym: str, direction: str) -> dict:
    """Totales del mes para emitidas o recibidas: base (subtotal), IVA y retenciones."""
    conn = db()
    try:
        base_where = (
            "issuer_id = ? AND direction = ? AND fecha_emision IS NOT NULL AND substr(fecha_emision,1,7) = ?"
        )
        if direction == "issued":
            base_where += " AND (total IS NULL OR total >= 0.01)"
        else:
            base_where += " AND total IS NOT NULL AND total >= 0.01 AND (tipo_comprobante IS NULL OR UPPER(TRIM(tipo_comprobante)) != 'N')"
        params = (issuer_id, direction, ym)
        has_retenciones = has_column(conn, "sat_cfdi", "retenciones")
        if has_retenciones:
            row = conn.execute(
                f"""
                SELECT
                    COALESCE(SUM(COALESCE(subtotal, total)), 0) AS total_base,
                    COALESCE(SUM(COALESCE(impuestos, 0)), 0) AS total_iva,
                    COALESCE(SUM(COALESCE(retenciones, 0)), 0) AS total_retenciones
                FROM sat_cfdi
                WHERE {base_where}
                """,
                params,
            ).fetchone()
        else:
            row = conn.execute(
                f"""
                SELECT
                    COALESCE(SUM(COALESCE(subtotal, total)), 0) AS total_base,
                    COALESCE(SUM(COALESCE(impuestos, 0)), 0) AS total_iva
                FROM sat_cfdi
                WHERE {base_where}
                """,
                params,
            ).fetchone()
        total_base = float(row[0] or 0) if row else 0.0
        total_iva = float(row[1] or 0) if row else 0.0
        total_retenciones = float(row[2] or 0) if (has_retenciones and row and len(row) >= 3) else 0.0
        return {
            "total_base": total_base,
            "total_iva": total_iva,
            "total_retenciones": total_retenciones,
            "total_iva_neto": max(0.0, total_iva - total_retenciones) if direction == "issued" else total_iva,
        }
    finally:
        conn.close()


def _safe_abs_path(path_like: str) -> str:
    """Resolve a stored path to an absolute path under BASE_DIR (prevent path traversal)."""
    if not path_like:
        raise ValueError("XML no disponible")
    p = path_like
    if not os.path.isabs(p):
        p = os.path.join(BASE_DIR, p)
    abs_p = os.path.abspath(p)
    base = os.path.abspath(BASE_DIR)
    if not abs_p.startswith(base + os.sep):
        raise ValueError("Ruta XML inválida")
    return abs_p


def _get_cfdi_by_uuid(issuer_id: int, uuid: str, direction: str):
    """Obtiene un CFDI de sat_cfdi por (issuer_id, uuid). direction: 'issued' o 'received'. Búsqueda por UUID case-insensitive."""
    u = (uuid or "").strip()
    if not u:
        return None
    conn = db()
    row = conn.execute(
        """
        SELECT uuid, fecha_emision, rfc_emisor, nombre_emisor, rfc_receptor, nombre_receptor,
               total, moneda, tipo_comprobante, status, xml_path, xml_status,
               serie, folio, forma_pago, metodo_pago, uso_cfdi, concepto,
               subtotal, descuento, impuestos, COALESCE(retenciones, 0) AS retenciones
        FROM sat_cfdi
        WHERE issuer_id = ? AND LOWER(TRIM(uuid)) = LOWER(?) AND direction = ?
        LIMIT 1
        """,
        (issuer_id, u, direction),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_portal_router(templates):
    """Build portal router with all /portal/* HTML routes. Requires Jinja2 templates instance."""

    def _render_portal(
        request: Request,
        *,
        issuer: dict,
        template_name: str,
        active_page: str,
        title: str,
        extra: Optional[dict] = None,
        error: Optional[str] = None,
    ):
        has_nomina = False
        if issuer.get("id", 0) > 0:
            r = db_rows(
                "SELECT 1 FROM sat_cfdi WHERE issuer_id = ? AND direction = 'received' AND UPPER(TRIM(COALESCE(tipo_comprobante,''))) = 'N' LIMIT 1",
                (issuer["id"],),
            )
            has_nomina = bool(r)
        regimen_label = issuer.get("regimen_fiscal") or ""
        issuer_tax_code = REGIMEN_LABEL_TO_CODE.get(regimen_label) if regimen_label else ""
        show_welcome_popup = getattr(request.state, "issuer_is_placeholder", False) and not getattr(
            request.state, "is_demo_view", False
        )
        is_demo_view = getattr(request.state, "is_demo_view", False)
        is_impersonating = getattr(request.state, "is_impersonating", False)
        payload = {
            "request": request,
            "token": "",
            "issuer_alias": issuer["alias"],
            "issuer_rfc": issuer["rfc"],
            "issuer_tax_system": issuer_tax_code,
            "issuer_regimen_label": regimen_label or "",
            "active_page": active_page,
            "title": title,
            "error": error,
            "has_nomina": has_nomina,
            "show_welcome_popup": show_welcome_popup,
            "is_demo_view": is_demo_view,
            "is_impersonating": is_impersonating,
        }
        if extra:
            payload.update(extra)
        return templates.TemplateResponse(template_name, payload)

    def _portal_quotations_impl(request: Request, issuer: dict):
        try:
            return _render_portal(
                request,
                issuer=issuer,
                template_name="portal_quotations.html",
                active_page="quotations",
                title="Cotizaciones",
            )
        except Exception as e:
            return HTMLResponse(
                f"<h3>Error</h3><p>No se pudo cargar la página de cotizaciones.</p><p><small>{str(e)}</small></p>",
                status_code=400,
            )

    router = APIRouter(prefix="/portal", tags=["portal"])

    @router.get("")
    def portal_root():
        return RedirectResponse(url="/portal/home", status_code=302)

    @router.get("/set-demo-view", response_class=RedirectResponse)
    def portal_set_demo_view(request: Request, _: dict = Depends(get_portal_issuer)):
        resp = RedirectResponse(url="/portal/home", status_code=302)
        resp.set_cookie(COOKIE_DEMO_VIEW, "1", max_age=86400 * 7, path="/", samesite="lax")
        return resp

    @router.get("/exit-demo-view", response_class=RedirectResponse)
    def portal_exit_demo_view(request: Request):
        resp = RedirectResponse(url="/portal/home", status_code=302)
        resp.delete_cookie(COOKIE_DEMO_VIEW, path="/")
        return resp

    @router.get("/quotations", response_class=HTMLResponse)
    @router.get("/cotizaciones", response_class=HTMLResponse)
    def portal_quotations(request: Request, issuer: dict = Depends(get_portal_issuer)):
        return _portal_quotations_impl(request, issuer)

    @router.get("/cotizaciones/ping")
    def portal_cotizaciones_ping():
        return Response(content="cotizaciones-ok", media_type="text/plain")

    @router.get("/quotations/{qid}/pdf")
    def portal_quotation_pdf(
        request: Request,
        qid: int,
        issuer: dict = Depends(get_portal_issuer),
        download: str = Query("0", alias="download"),
    ):
        conn = db()
        row = conn.execute(
            "SELECT id, public_token FROM quotations WHERE issuer_id = ? AND id = ?",
            (issuer["id"], qid),
        ).fetchone()
        if not row:
            conn.close()
            raise HTTPException(status_code=404, detail="Cotización no encontrada")
        conn.close()
        quote = quotations_service.get_quotation_by_public_token(dict(row)["public_token"])
        if not quote:
            raise HTTPException(status_code=404, detail="Cotización no encontrada")
        cookie_val = request.cookies.get(session_service.get_session_cookie_name())
        data = session_service.verify_session(cookie_val)
        uid = data[0] if data and len(data) >= 1 else None
        audit.log(action="quotation_pdf", user_id=uid, issuer_id=issuer["id"], details=f"qid={qid}")
        try:
            pdf_bytes = quotations_service.build_quotation_pdf(quote)
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
        disposition = "attachment" if download == "1" else "inline"
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'{disposition}; filename="cotizacion-{qid}.pdf"'},
        )

    @router.get("/quotations/{qid}", response_class=HTMLResponse)
    def portal_quotation_detail(request: Request, qid: int, issuer: dict = Depends(get_portal_issuer)):
        conn = db()
        row = conn.execute(
            "SELECT id, public_token, folio, customer_rfc, customer_legal_name, customer_email, status, notes, responded_at, created_at FROM quotations WHERE issuer_id = ? AND id = ?",
            (issuer["id"], qid),
        ).fetchone()
        conn.close()
        if not row:
            raise HTTPException(status_code=404, detail="Cotización no encontrada")
        d = dict(row)
        quote = quotations_service.get_quotation_by_public_token(d["public_token"])
        if not quote:
            raise HTTPException(status_code=404, detail="Cotización no encontrada")
        return _render_portal(
            request,
            issuer=issuer,
            template_name="quote_detail.html",
            active_page="quotations",
            title="Cotización",
            extra={"quote": quote},
        )

    @router.get("/home", response_class=HTMLResponse)
    def portal_home(request: Request, issuer: dict = Depends(get_portal_issuer)):
        try:
            issuer_id = issuer["id"]
            ym = ym_now()
            count_issued = db_rows(
                """
                SELECT COUNT(*) AS n FROM sat_cfdi
                WHERE issuer_id = ? AND direction = 'issued' AND fecha_emision IS NOT NULL
                  AND substr(fecha_emision,1,7) = ? AND (total IS NULL OR total >= 0.01)
                """,
                (issuer_id, ym),
            )
            count_received = db_rows(
                """
                SELECT COUNT(*) AS n FROM sat_cfdi
                WHERE issuer_id = ? AND direction = 'received' AND fecha_emision IS NOT NULL
                  AND substr(fecha_emision,1,7) = ? AND total IS NOT NULL AND total >= 0.01
                  AND (tipo_comprobante IS NULL OR UPPER(TRIM(tipo_comprobante)) != 'N')
                """,
                (issuer_id, ym),
            )
            tot_issued = _get_month_totals(issuer_id, ym, "issued")
            tot_received = _get_month_totals(issuer_id, ym, "received")
            ingresos_sin_iva = tot_issued["total_base"]
            gastos_sin_iva = tot_received["total_base"]
            iva_retenciones = tot_issued["total_retenciones"]
            iva_recibido_neto = tot_issued["total_iva_neto"]
            iva_pagado = tot_received["total_iva"]
            activities = db_rows(
                """
                SELECT direction, fecha_emision, nombre FROM (
                  SELECT direction, fecha_emision, nombre_receptor AS nombre FROM sat_cfdi
                  WHERE issuer_id = ? AND direction = 'issued' AND fecha_emision IS NOT NULL
                    AND (total IS NULL OR total >= 0.01)
                  UNION ALL
                  SELECT direction, fecha_emision, nombre_emisor AS nombre FROM sat_cfdi
                  WHERE issuer_id = ? AND direction = 'received' AND fecha_emision IS NOT NULL
                    AND total IS NOT NULL AND total >= 0.01
                    AND (tipo_comprobante IS NULL OR UPPER(TRIM(tipo_comprobante)) != 'N')
                ) ORDER BY fecha_emision DESC LIMIT 3
                """,
                (issuer_id, issuer_id),
            )
            today = date.today()
            for a in activities:
                try:
                    fd = datetime.strptime((a["fecha_emision"] or "")[:10], "%Y-%m-%d").date()
                    d = (today - fd).days
                    a["time_ago"] = "Hoy" if d == 0 else "Ayer" if d == 1 else f"Hace {d} días"
                except (ValueError, TypeError):
                    a["time_ago"] = a.get("fecha_emision", "")[:10] or "-"
            return _render_portal(
                request,
                issuer=issuer,
                template_name="portal_home.html",
                active_page="home",
                title="Inicio",
                extra={
                    "count_issued": count_issued[0]["n"] if count_issued else 0,
                    "count_received": count_received[0]["n"] if count_received else 0,
                    "activities": activities,
                    "ym_label": ym_to_label(ym),
                    "ym": ym,
                    "ingresos_sin_iva": ingresos_sin_iva,
                    "gastos_sin_iva": gastos_sin_iva,
                    "iva_recibido_neto": iva_recibido_neto,
                    "iva_retenciones": iva_retenciones,
                    "iva_pagado": iva_pagado,
                },
            )
        except Exception as e:
            return HTMLResponse(f"<h3>Error</h3><p>{str(e)}</p>", status_code=400)

    @router.get("/create", response_class=HTMLResponse)
    def portal_create(
        request: Request,
        issuer: dict = Depends(get_portal_issuer),
        quote_id: Optional[int] = Query(None),
        customer_rfc: Optional[str] = Query(None),
        customer_legal_name: Optional[str] = Query(None),
        customer_zip: Optional[str] = Query(None),
        customer_tax_system: Optional[str] = Query(None),
        customer_email: Optional[str] = Query(None),
        concept_desc: Optional[str] = Query(None),
        concept_key: Optional[str] = Query(None),
        concept_unit: Optional[str] = Query(None),
        concept_price: Optional[str] = Query(None),
        concept_iva: Optional[str] = Query(None),
    ):
        customer_prefill = None
        concept_prefill = None
        quote_items = None
        if quote_id is not None:
            try:
                conn = db()
                row = conn.execute(
                    "SELECT customer_rfc, customer_legal_name, customer_email FROM quotations WHERE issuer_id = ? AND id = ?",
                    (issuer["id"], quote_id),
                ).fetchone()
                if row:
                    r = dict(row)
                    customer_prefill = {
                        "customer_rfc": (r.get("customer_rfc") or "").strip(),
                        "customer_legal_name": (r.get("customer_legal_name") or "").strip(),
                        "customer_zip": "",
                        "customer_tax_system": "",
                        "customer_email": (r.get("customer_email") or "").strip(),
                    }
                    items = conn.execute(
                        "SELECT description, quantity, unit_price, iva_rate FROM quotation_items WHERE quotation_id = ? ORDER BY sort_order, id",
                        (quote_id,),
                    ).fetchall()
                    conn.close()
                    quote_items = [
                        {
                            "description": x["description"],
                            "quantity": float(x["quantity"] or 0),
                            "unit_price": float(x["unit_price"] or 0),
                            "iva_rate": float(x["iva_rate"] or 0.16),
                        }
                        for x in items
                    ]
                    if quote_items:
                        concept_prefill = {
                            "description": quote_items[0]["description"],
                            "product_key": "",
                            "unit_key": "E48",
                            "unit_price": str(quote_items[0]["unit_price"]),
                            "iva_rate": str(quote_items[0]["iva_rate"]),
                        }
                else:
                    conn.close()
            except ValueError:
                pass
        if customer_prefill is None and (customer_rfc or customer_legal_name or customer_zip or customer_tax_system or customer_email):
            customer_prefill = {
                "customer_rfc": (customer_rfc or "").strip(),
                "customer_legal_name": (customer_legal_name or "").strip(),
                "customer_zip": (customer_zip or "").strip(),
                "customer_tax_system": (customer_tax_system or "").strip(),
                "customer_email": (customer_email or "").strip(),
            }
        if concept_prefill is None and (concept_desc or concept_key or concept_unit or concept_price or concept_iva):
            concept_prefill = {
                "description": (concept_desc or "").strip(),
                "product_key": (concept_key or "").strip(),
                "unit_key": (concept_unit or "").strip() or "E48",
                "unit_price": (concept_price or "").strip(),
                "iva_rate": (concept_iva or "0.16").strip(),
            }
        try:
            return _render_portal(
                request,
                issuer=issuer,
                template_name="form.html",
                active_page="create",
                title="Factura nueva",
                extra={
                    "create_mode": "normal",
                    "customer_prefill": customer_prefill,
                    "concept_prefill": concept_prefill,
                    "quote_items": quote_items,
                    "csrf_token": csrf_service.generate_csrf_token(),
                },
            )
        except Exception as e:
            return HTMLResponse(f"<h3>Error</h3><p>{str(e)}</p>", status_code=400)

    @router.get("/create/quick", response_class=HTMLResponse)
    def portal_create_quick(request: Request, issuer: dict = Depends(get_portal_issuer)):
        try:
            return _render_portal(
                request, issuer=issuer, template_name="form.html", active_page="create_quick", title="Factura rápida", extra={"create_mode": "quick", "csrf_token": csrf_service.generate_csrf_token()}
            )
        except Exception as e:
            return HTMLResponse(f"<h3>Error</h3><p>{str(e)}</p>", status_code=400)

    @router.get("/create/multi", response_class=HTMLResponse)
    def portal_create_multi(request: Request, issuer: dict = Depends(get_portal_issuer)):
        try:
            return _render_portal(
                request, issuer=issuer, template_name="form.html", active_page="create_multi", title="Factura múltiple", extra={"create_mode": "multi", "csrf_token": csrf_service.generate_csrf_token()}
            )
        except Exception as e:
            return HTMLResponse(f"<h3>Error</h3><p>{str(e)}</p>", status_code=400)

    @router.get("/invoices", response_class=HTMLResponse)
    def portal_invoices(request: Request, issuer: dict = Depends(get_portal_issuer)):
        try:
            return _render_portal(
                request, issuer=issuer, template_name="portal_invoices.html", active_page="issued", title="Mis facturas"
            )
        except Exception as e:
            return HTMLResponse(f"<h3>Error</h3><p>{str(e)}</p>", status_code=400)

    @router.get("/invoices/issued", response_class=HTMLResponse)
    def portal_invoices_issued(request: Request, issuer: dict = Depends(get_portal_issuer), ym: str = None):
        try:
            issuer_id = issuer["id"]
            if not ym:
                ym = ym_now()
            rows = db_rows("""
                SELECT uuid, fecha_emision, rfc_receptor, nombre_receptor, total, moneda, status, xml_path,
                       serie, folio, concepto, forma_pago, metodo_pago, uso_cfdi, subtotal, descuento, impuestos,
                       COALESCE(retenciones, 0) AS retenciones,
                       tipo_comprobante, xml_status
                FROM sat_cfdi
                WHERE issuer_id = ? AND direction = 'issued' AND fecha_emision IS NOT NULL
                  AND substr(fecha_emision,1,7) = ? AND (total IS NULL OR total >= 0.01)
                  AND xml_path IS NOT NULL AND TRIM(COALESCE(xml_path,'')) != ''
                  AND id IN (
                    SELECT id FROM (
                      SELECT id, ROW_NUMBER() OVER (
                        PARTITION BY issuer_id, direction, LOWER(TRIM(uuid))
                        ORDER BY (CASE WHEN COALESCE(total,0) >= 0.01 THEN 0 ELSE 1 END), id
                      ) AS rn
                      FROM sat_cfdi
                      WHERE issuer_id = ? AND direction = 'issued' AND fecha_emision IS NOT NULL AND substr(fecha_emision,1,7) = ? AND (total IS NULL OR total >= 0.01)
                        AND xml_path IS NOT NULL AND TRIM(COALESCE(xml_path,'')) != ''
                    ) WHERE rn = 1
                  )
                ORDER BY fecha_emision DESC LIMIT 300;
            """, (issuer_id, ym, issuer_id, ym))
            months = db_rows("""
                SELECT substr(fecha_emision,1,7) AS ym, count(*) AS n
                FROM sat_cfdi
                WHERE issuer_id = ? AND direction = 'issued' AND fecha_emision IS NOT NULL
                  AND (total IS NULL OR total >= 0.01)
                  AND xml_path IS NOT NULL AND TRIM(COALESCE(xml_path,'')) != ''
                GROUP BY ym ORDER BY ym DESC;
            """, (issuer_id,))
            for m in months:
                m["label"] = ym_to_label(m["ym"])
            month_totals = _get_month_totals(issuer_id, ym, "issued")
            return _render_portal(
                request,
                issuer=issuer,
                template_name="portal_issued.html",
                active_page="issued",
                title="Facturas emitidas",
                extra={
                    "rows": rows,
                    "ym": ym,
                    "ym_label": ym_to_label(ym),
                    "prev_ym": shift_ym(ym, -1),
                    "next_ym": shift_ym(ym, +1),
                    "months": months,
                    "month_totals": month_totals,
                },
            )
        except Exception as e:
            return HTMLResponse(f"<h3>Error</h3><p>{str(e)}</p>", status_code=400)

    @router.get("/invoices/received", response_class=HTMLResponse)
    def portal_invoices_received(request: Request, issuer: dict = Depends(get_portal_issuer), ym: str = None):
        try:
            issuer_id = issuer["id"]
            if not ym:
                ym = ym_now()
            rows = db_rows("""
                SELECT uuid, fecha_emision, rfc_emisor, nombre_emisor, total, moneda, status, xml_path,
                       serie, folio, concepto, forma_pago, metodo_pago, uso_cfdi, subtotal, descuento, impuestos,
                       COALESCE(retenciones, 0) AS retenciones,
                       tipo_comprobante, xml_status
                FROM sat_cfdi
                WHERE issuer_id = ? AND direction = 'received' AND fecha_emision IS NOT NULL
                  AND substr(fecha_emision,1,7) = ? AND total IS NOT NULL AND total >= 0.01
                  AND (tipo_comprobante IS NULL OR UPPER(TRIM(tipo_comprobante)) != 'N')
                  AND xml_path IS NOT NULL AND TRIM(COALESCE(xml_path,'')) != ''
                  AND id IN (
                    SELECT id FROM (
                      SELECT id, ROW_NUMBER() OVER (
                        PARTITION BY issuer_id, direction, LOWER(TRIM(uuid))
                        ORDER BY id
                      ) AS rn
                      FROM sat_cfdi
                      WHERE issuer_id = ? AND direction = 'received' AND fecha_emision IS NOT NULL AND substr(fecha_emision,1,7) = ? AND total IS NOT NULL AND total >= 0.01 AND (tipo_comprobante IS NULL OR UPPER(TRIM(tipo_comprobante)) != 'N')
                        AND xml_path IS NOT NULL AND TRIM(COALESCE(xml_path,'')) != ''
                    ) WHERE rn = 1
                  )
                ORDER BY fecha_emision DESC LIMIT 300;
            """, (issuer_id, ym, issuer_id, ym))
            months = db_rows("""
                SELECT substr(fecha_emision,1,7) AS ym, count(*) AS n
                FROM sat_cfdi
                WHERE issuer_id = ? AND direction = 'received' AND fecha_emision IS NOT NULL
                  AND total IS NOT NULL AND total >= 0.01
                  AND (tipo_comprobante IS NULL OR UPPER(TRIM(tipo_comprobante)) != 'N')
                  AND xml_path IS NOT NULL AND TRIM(COALESCE(xml_path,'')) != ''
                GROUP BY ym ORDER BY ym DESC;
            """, (issuer_id,))
            for m in months:
                m["label"] = ym_to_label(m["ym"])
            month_totals = _get_month_totals(issuer_id, ym, "received")
            return _render_portal(
                request,
                issuer=issuer,
                template_name="portal_received.html",
                active_page="received",
                title="Facturas recibidas",
                extra={
                    "rows": rows,
                    "ym": ym,
                    "ym_label": ym_to_label(ym),
                    "prev_ym": shift_ym(ym, -1),
                    "next_ym": shift_ym(ym, +1),
                    "months": months,
                    "month_totals": month_totals,
                },
            )
        except Exception as e:
            return HTMLResponse(f"<h3>Error</h3><p>{str(e)}</p>", status_code=400)

    @router.get("/invoices/nomina", response_class=HTMLResponse)
    def portal_invoices_nomina(request: Request, issuer: dict = Depends(get_portal_issuer), ym: str = None):
        try:
            issuer_id = issuer["id"]
            if not ym:
                ym = ym_now()
            rows = db_rows("""
                SELECT uuid, fecha_emision, rfc_emisor, nombre_emisor, total, moneda, status, xml_path,
                       serie, folio, concepto, forma_pago, metodo_pago, uso_cfdi, subtotal, descuento, impuestos,
                       tipo_comprobante, xml_status
                FROM sat_cfdi
                WHERE issuer_id = ? AND direction = 'received'
                  AND UPPER(TRIM(COALESCE(tipo_comprobante,''))) = 'N'
                  AND fecha_emision IS NOT NULL AND substr(fecha_emision,1,7) = ?
                  AND xml_path IS NOT NULL AND TRIM(COALESCE(xml_path,'')) != ''
                ORDER BY fecha_emision DESC LIMIT 300;
            """, (issuer_id, ym))
            months = db_rows("""
                SELECT substr(fecha_emision,1,7) AS ym, count(*) AS n
                FROM sat_cfdi
                WHERE issuer_id = ? AND direction = 'received'
                  AND UPPER(TRIM(COALESCE(tipo_comprobante,''))) = 'N'
                  AND fecha_emision IS NOT NULL
                  AND xml_path IS NOT NULL AND TRIM(COALESCE(xml_path,'')) != ''
                GROUP BY ym ORDER BY ym DESC;
            """, (issuer_id,))
            for m in months:
                m["label"] = ym_to_label(m["ym"])
            return _render_portal(
                request,
                issuer=issuer,
                template_name="portal_nomina.html",
                active_page="nomina",
                title="Nómina recibida",
                extra={
                    "rows": rows,
                    "ym": ym,
                    "ym_label": ym_to_label(ym),
                    "prev_ym": shift_ym(ym, -1),
                    "next_ym": shift_ym(ym, +1),
                    "months": months,
                },
            )
        except Exception as e:
            return HTMLResponse(f"<h3>Error</h3><p>{str(e)}</p>", status_code=400)

    def _audit_user_issuer(request: Request):
        cookie_val = request.cookies.get(session_service.get_session_cookie_name())
        data = session_service.verify_session(cookie_val)
        user_id = data[0] if data and len(data) >= 1 else None
        issuer_id = data[1] if data and len(data) >= 2 else None
        return user_id, issuer_id

    @router.get("/sat/xml/{uuid}")
    def portal_sat_xml(request: Request, uuid: str, issuer: dict = Depends(get_portal_issuer)):
        u = (uuid or "").strip()
        if not u:
            raise HTTPException(status_code=404, detail="UUID no válido")
        conn = db()
        row = conn.execute(
            "SELECT xml_path, uuid FROM sat_cfdi WHERE issuer_id = ? AND LOWER(TRIM(uuid)) = LOWER(?) LIMIT 1",
            (issuer["id"], u),
        ).fetchone()
        conn.close()
        if not row or not row["xml_path"]:
            raise HTTPException(status_code=404, detail="XML no encontrado para este UUID")
        try:
            abs_path = _safe_abs_path(row["xml_path"])
        except ValueError:
            raise HTTPException(status_code=404, detail="Ruta XML inválida")
        if not os.path.exists(abs_path):
            raise HTTPException(status_code=404, detail="Archivo XML no existe en disco")
        uid, iid = _audit_user_issuer(request)
        if uid and uid > 0 and not subscription_service.is_subscription_active(uid):
            raise HTTPException(status_code=402, detail="Actualiza a Pro para descargar XML. Ve a Mi plan.")
        audit.log(action="download_xml", user_id=uid, issuer_id=issuer["id"], details=u[:36])
        with open(abs_path, "rb") as f:
            xml_bytes = f.read()
        return Response(
            content=xml_bytes,
            media_type="application/xml",
            headers={"Content-Disposition": f'inline; filename="{row["uuid"]}.xml"'},
        )

    @router.get("/sat/pdf/{uuid}")
    def portal_sat_pdf(request: Request, uuid: str, issuer: dict = Depends(get_portal_issuer), dl: int = 0):
        uuid_clean = (uuid or "").strip().split()[0] if uuid else ""
        if not uuid_clean:
            raise HTTPException(status_code=404, detail="UUID no válido")
        conn = db()
        row = conn.execute(
            "SELECT xml_path, uuid FROM sat_cfdi WHERE issuer_id = ? AND LOWER(TRIM(uuid)) = LOWER(?) LIMIT 1",
            (issuer["id"], uuid_clean),
        ).fetchone()
        conn.close()
        if not row or not row["xml_path"]:
            raise HTTPException(status_code=404, detail="XML no encontrado para este UUID")
        try:
            abs_path = _safe_abs_path(row["xml_path"])
        except ValueError:
            raise HTTPException(status_code=404, detail="Ruta XML inválida")
        if not os.path.exists(abs_path):
            raise HTTPException(status_code=404, detail="Archivo XML no existe en disco")
        uid, _ = _audit_user_issuer(request)
        if uid and uid > 0 and not subscription_service.is_subscription_active(uid):
            raise HTTPException(status_code=402, detail="Actualiza a Pro para descargar PDF. Ve a Mi plan.")
        audit.log(action="download_pdf", user_id=uid, issuer_id=issuer["id"], details=uuid_clean[:36])
        try:
            from cfdi_pdf import parse_cfdi_xml, build_pdf
            data = parse_cfdi_xml(abs_path)
            pdf_bytes = build_pdf(data)
        except Exception as e:
            err_msg = str(e)
            hint = " Instala dependencias: pip install -r requirements.txt" if "reportlab" in err_msg.lower() else ""
            return HTMLResponse(
                f'<!DOCTYPE html><html><head><meta charset="utf-8"><title>Error PDF</title></head>'
                f'<body id="pdf-error" style="margin:1rem;font-family:system-ui,sans-serif;">'
                f'<p id="pdf-error-msg">No se pudo generar el PDF: {err_msg}</p>'
                f'<p class="pdf-error-hint" style="color:#666;">{hint}</p></body></html>',
                status_code=500,
            )
        if not pdf_bytes:
            raise HTTPException(status_code=500, detail="La generación del PDF devolvió vacío")
        filename = f"cfdi-{uuid_clean[:8]}.pdf"
        disposition = "attachment" if dl else "inline"
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'{disposition}; filename="{filename}"',
                "Content-Length": str(len(pdf_bytes)),
            },
        )

    @router.get("/cfdi/issued/{uuid}", response_class=HTMLResponse)
    def portal_cfdi_detail_issued(request: Request, uuid: str, issuer: dict = Depends(get_portal_issuer)):
        cfdi = _get_cfdi_by_uuid(issuer["id"], uuid, "issued")
        if not cfdi:
            raise HTTPException(status_code=404, detail="CFDI no encontrado")
        uid = getattr(request.state, "user_id", None) or 0
        audit.log(action="cfdi_view", user_id=uid if uid else None, issuer_id=issuer["id"], details=f"direction=issued uuid={(uuid or '')[:36]}")
        return _render_portal(
            request,
            issuer=issuer,
            template_name="portal_cfdi_detail.html",
            active_page="issued",
            title="Detalle CFDI emitido",
            extra={"cfdi": cfdi, "direction": "issued"},
        )

    @router.get("/cfdi/received/{uuid}", response_class=HTMLResponse)
    def portal_cfdi_detail_received(request: Request, uuid: str, issuer: dict = Depends(get_portal_issuer)):
        cfdi = _get_cfdi_by_uuid(issuer["id"], uuid, "received")
        if not cfdi:
            raise HTTPException(status_code=404, detail="CFDI no encontrado")
        uid = getattr(request.state, "user_id", None) or 0
        audit.log(action="cfdi_view", user_id=uid if uid else None, issuer_id=issuer["id"], details=f"direction=received uuid={(uuid or '')[:36]}")
        return _render_portal(
            request,
            issuer=issuer,
            template_name="portal_cfdi_detail.html",
            active_page="received",
            title="Detalle CFDI recibido",
            extra={"cfdi": cfdi, "direction": "received"},
        )

    @router.get("/clients", response_class=HTMLResponse)
    def portal_clients(request: Request, issuer: dict = Depends(get_portal_issuer)):
        try:
            return _render_portal(
                request, issuer=issuer, template_name="portal_clients.html", active_page="clients", title="Clientes"
            )
        except Exception as e:
            return HTMLResponse(f"<h3>Error</h3><p>{str(e)}</p>", status_code=400)

    @router.get("/providers", response_class=HTMLResponse)
    def portal_providers(request: Request, issuer: dict = Depends(get_portal_issuer)):
        try:
            return _render_portal(
                request, issuer=issuer, template_name="portal_providers.html", active_page="providers", title="Proveedores"
            )
        except Exception as e:
            return HTMLResponse(f"<h3>Error</h3><p>{str(e)}</p>", status_code=400)

    @router.get("/products", response_class=HTMLResponse)
    def portal_products(request: Request, issuer: dict = Depends(get_portal_issuer)):
        try:
            return _render_portal(
                request, issuer=issuer, template_name="portal_products.html", active_page="products", title="Productos"
            )
        except Exception as e:
            return HTMLResponse(f"<h3>Error</h3><p>{str(e)}</p>", status_code=400)

    @router.get("/summary", response_class=HTMLResponse)
    def portal_summary(request: Request, issuer: dict = Depends(get_portal_issuer), ym: str = None):
        try:
            issuer_id = issuer["id"]
            if not ym:
                ym = ym_now()
            tot_issued = _get_month_totals(issuer_id, ym, "issued")
            tot_received = _get_month_totals(issuer_id, ym, "received")
            ingresos_sin_iva = tot_issued["total_base"]
            gastos_sin_iva = tot_received["total_base"]
            iva_retenciones = tot_issued["total_retenciones"]
            iva_recibido_neto = tot_issued["total_iva_neto"]
            iva_pagado = tot_received["total_iva"]
            months_issued = db_rows(
                """
                SELECT substr(fecha_emision,1,7) AS ym, count(*) AS n
                FROM sat_cfdi
                WHERE issuer_id = ? AND direction = 'issued' AND fecha_emision IS NOT NULL
                GROUP BY ym ORDER BY ym DESC
                """,
                (issuer_id,),
            )
            months_received = db_rows(
                """
                SELECT substr(fecha_emision,1,7) AS ym, count(*) AS n
                FROM sat_cfdi
                WHERE issuer_id = ? AND direction = 'received' AND fecha_emision IS NOT NULL
                GROUP BY ym ORDER BY ym DESC
                """,
                (issuer_id,),
            )
            ym_counts = {}
            for m in months_issued + months_received:
                ym_counts[m["ym"]] = ym_counts.get(m["ym"], 0) + m["n"]
            if ym not in ym_counts:
                ym_counts[ym] = 0
            months = [{"ym": y, "n": n, "label": ym_to_label(y)} for y, n in sorted(ym_counts.items(), reverse=True)]
            return _render_portal(
                request,
                issuer=issuer,
                template_name="portal_summary.html",
                active_page="summary",
                title="Resumen",
                extra={
                    "ym": ym,
                    "ym_label": ym_to_label(ym),
                    "prev_ym": shift_ym(ym, -1),
                    "next_ym": shift_ym(ym, +1),
                    "months": months,
                    "ingresos_sin_iva": ingresos_sin_iva,
                    "gastos_sin_iva": gastos_sin_iva,
                    "iva_recibido_neto": iva_recibido_neto,
                    "iva_retenciones": iva_retenciones,
                    "iva_pagado": iva_pagado,
                },
            )
        except Exception as e:
            return HTMLResponse(f"<h3>Error</h3><p>{str(e)}</p>", status_code=400)

    @router.get("/plan", response_class=HTMLResponse)
    def portal_plan(request: Request, issuer: dict = Depends(get_portal_issuer), success: str = Query(""), canceled: str = Query("")):
        user_id = getattr(request.state, "user_id", None) or 0
        subscription = subscription_service.get_subscription_by_user_id(user_id) if user_id else None
        is_active = subscription_service.is_subscription_active(user_id)
        return _render_portal(
            request,
            issuer=issuer,
            template_name="portal_plan.html",
            active_page="plan",
            title="Mi plan",
            extra={
                "subscription": subscription,
                "is_active": is_active,
                "success": success == "1",
                "canceled": canceled == "1",
            },
        )

    return router
