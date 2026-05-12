"""Portal invoices routes."""
import io
import logging
import os
from typing import Optional

from fastapi import Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from database import db, db_rows
from routers.deps import get_portal_issuer
from routers.portal._helpers import (
    _get_cfdi_by_uuid,
    _safe_abs_path,
    render_portal,
    ym_now,
)
from services import audit, file_access_log
from services.action_log import log_action
from services.auth import csrf as csrf_service
from services.auth import session as session_service
from services.billing import subscription as subscription_service
from services.portal_errors import portal_error_type
from services.sat.sat_sync import get_month_totals, get_sat_sync_status
from services.ym_helpers import is_annual, sanitize_ym, shift_ym, ym_sql_filter, ym_to_label

logger = logging.getLogger(__name__)

_get_month_totals = get_month_totals
_get_sat_sync_status = get_sat_sync_status


def register_invoices_routes(router, templates):
    """Register Invoices routes on the portal router."""

    def _render_portal(request, **kwargs):
        return render_portal(templates, request, **kwargs)

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
        except Exception:
            logger.exception("portal: error renderizando /portal/create")
            raise

    @router.get("/create/quick", response_class=HTMLResponse)
    def portal_create_quick(
        request: Request,
        issuer: dict = Depends(get_portal_issuer),
        customer_id: Optional[int] = Query(None),
        product_id: Optional[int] = Query(None),
    ):
        # Sin cliente y producto: página para elegir (misma fuente que Clientes y Productos: /api/customers, /api/products)
        if customer_id is None or product_id is None:
            try:
                return _render_portal(
                    request,
                    issuer=issuer,
                    template_name="portal_create_quick_choose.html",
                    active_page="create",
                    title="Factura rápida",
                )
            except Exception:
                logger.exception("portal: error renderizando selector factura rápida")
                raise
        customer_prefill = None
        concept_prefill = None
        issuer_id = issuer["id"]
        cust = db_rows(
            "SELECT id, rfc, legal_name, zip, tax_system, email FROM customer_profiles WHERE issuer_id = ? AND id = ? LIMIT 1",
            (issuer_id, customer_id),
        )
        prod = db_rows(
            "SELECT id, description, product_key, unit_key, unit_price, iva_rate FROM issuer_products WHERE issuer_id = ? AND id = ? LIMIT 1",
            (issuer_id, product_id),
        )
        if cust and prod:
            c = cust[0]
            p = prod[0]
            customer_prefill = {
                "customer_rfc": (c.get("rfc") or "").strip(),
                "customer_legal_name": (c.get("legal_name") or "").strip(),
                "customer_zip": (c.get("zip") or "").strip(),
                "customer_tax_system": (c.get("tax_system") or "").strip(),
                "customer_email": (c.get("email") or "").strip(),
            }
            concept_prefill = {
                "description": (p.get("description") or "").strip(),
                "product_key": (p.get("product_key") or "").strip(),
                "unit_key": (p.get("unit_key") or "").strip() or "E48",
                "unit_price": str(p.get("unit_price") or ""),
                "iva_rate": str(p.get("iva_rate") or "0.16"),
            }
        try:
            return _render_portal(
                request,
                issuer=issuer,
                template_name="form.html",
                active_page="create_quick",
                title="Factura rápida",
                extra={
                    "create_mode": "quick",
                    "csrf_token": csrf_service.generate_csrf_token(),
                    "customer_prefill": customer_prefill,
                    "concept_prefill": concept_prefill,
                },
            )
        except Exception:
            logger.exception("portal: error renderizando /portal/create/quick")
            raise

    @router.get("/create/multi", response_class=HTMLResponse)
    def portal_create_multi(request: Request, issuer: dict = Depends(get_portal_issuer)):
        try:
            return _render_portal(
                request, issuer=issuer, template_name="form.html", active_page="create_multi", title="Factura múltiple", extra={"create_mode": "multi", "csrf_token": csrf_service.generate_csrf_token()}
            )
        except Exception:
            logger.exception("portal: error renderizando /portal/create/multi")
            raise

    @router.get("/invoices", response_class=HTMLResponse)
    def portal_invoices(request: Request, issuer: dict = Depends(get_portal_issuer)):
        try:
            return _render_portal(
                request, issuer=issuer, template_name="portal_invoices.html", active_page="issued", title="Mis facturas"
            )
        except Exception:
            logger.exception("portal: error renderizando /portal/invoices")
            raise

    @router.get("/invoices-ext", response_class=HTMLResponse)
    def portal_invoices_ext(
        request: Request,
        issuer: dict = Depends(get_portal_issuer),
        ym: str | None = Query(None),
    ):
        """Foreign invoices page."""
        try:
            issuer_id = int(issuer.get("id") or 0)
            if issuer_id <= 0:
                raise HTTPException(status_code=401, detail="Sesión inválida")
            if not ym:
                ym = ym_now()
            from services.invoices import foreign_invoices as fi
            fi.ensure_table()
            items = fi.list_invoices(issuer_id, period_month=ym, limit=200)
            total = fi.count_invoices(issuer_id, period_month=ym)
            sum_ingresos = sum(r.get("monto_mxn", 0) for r in items if r.get("tipo") == "INGRESO")
            sum_gastos = sum(r.get("monto_mxn", 0) for r in items if r.get("tipo") == "GASTO")
            prev_ym = shift_ym(ym, -1)
            next_ym = shift_ym(ym, 1)
            return _render_portal(
                request,
                issuer=issuer,
                template_name="portal_invoices_ext.html",
                active_page="invoices_ext",
                title="Invoices Extranjeros",
                extra={
                    "invoices": items,
                    "total_count": total,
                    "sum_ingresos": sum_ingresos,
                    "sum_gastos": sum_gastos,
                    "ym": ym,
                    "ym_label": ym_to_label(ym),
                    "prev_ym": prev_ym,
                    "next_ym": next_ym,
                },
            )
        except HTTPException:
            raise
        except Exception:
            logger.exception("portal: error renderizando /portal/invoices-ext")
            raise

    @router.get("/invoices/issued", response_class=RedirectResponse)
    def portal_invoices_issued(ym: str = None):
        """Redirect legacy /invoices/issued to /facturas hub."""
        url = f"/portal/facturas?tab=issued&ym={ym}" if ym else "/portal/facturas?tab=issued"
        return RedirectResponse(url=url, status_code=301)

    @router.get("/invoices/received", response_class=RedirectResponse)
    def portal_invoices_received(ym: str = None):
        """Redirect legacy /invoices/received to /facturas hub."""
        url = f"/portal/facturas?tab=received&ym={ym}" if ym else "/portal/facturas?tab=received"
        return RedirectResponse(url=url, status_code=301)

    # ---------- Hubs (navegación agrupada con tabs) ----------
    @router.get("/facturas", response_class=HTMLResponse)
    def portal_facturas_hub(
        request: Request,
        issuer: dict = Depends(get_portal_issuer),
        tab: str = Query("issued", description="issued|received|ppd"),
        ym: str = None,
    ):
        """Hub Facturas: tabs Emitidas / Recibidas / PPD. Reutiliza misma lógica y datos que rutas legacy."""
        try:
            if tab not in ("issued", "received", "ppd"):
                tab = "issued"
            issuer_id = issuer["id"]
            if not ym:
                ym = ym_now()
            ym = sanitize_ym(ym, ym_now())
            _ym_filt = ym_sql_filter(ym)
            _row_limit = 3000 if is_annual(ym) else 300
            month_picker_base_url = f"/portal/facturas?tab={tab}"
            sat_sync_status = _get_sat_sync_status(issuer_id)
            has_fiel_validated = bool(db_rows("SELECT 1 FROM sat_credentials WHERE issuer_id = ? AND validation_ok = 1 LIMIT 1", (issuer_id,)))
            base_extra = {
                "ym": ym,
                "ym_label": ym_to_label(ym),
                "prev_ym": shift_ym(ym, -1),
                "next_ym": shift_ym(ym, +1),
                "sat_sync_status": sat_sync_status,
                "has_fiel_validated": has_fiel_validated,
                "month_picker_base_url": month_picker_base_url,
            }
            if tab == "issued":
                rows = db_rows(f"""
                    SELECT uuid, fecha_emision, rfc_receptor, nombre_receptor, concepto, total, moneda,
                           COALESCE(impuestos, 0) AS impuestos, COALESCE(retenciones, 0) AS retenciones,
                           metodo_pago, status, xml_path
                    FROM sat_cfdi
                    WHERE issuer_id = ? AND direction = 'issued' AND fecha_emision IS NOT NULL
                      AND {_ym_filt} AND (total IS NULL OR total >= 0.01)
                      AND id IN (
                        SELECT id FROM (
                          SELECT id, ROW_NUMBER() OVER (
                            PARTITION BY issuer_id, direction, LOWER(TRIM(uuid))
                            ORDER BY (CASE WHEN COALESCE(total,0) >= 0.01 THEN 0 ELSE 1 END), id
                          ) AS rn
                          FROM sat_cfdi
                          WHERE issuer_id = ? AND direction = 'issued' AND fecha_emision IS NOT NULL AND {_ym_filt} AND (total IS NULL OR total >= 0.01)
                        ) WHERE rn = 1
                      )
                    ORDER BY fecha_emision DESC LIMIT {_row_limit};
                """, (issuer_id, ym, issuer_id, ym))
                months = db_rows("""
                    SELECT substr(fecha_emision,1,7) AS ym, count(*) AS n
                    FROM sat_cfdi
                    WHERE issuer_id = ? AND direction = 'issued' AND fecha_emision IS NOT NULL
                      AND (total IS NULL OR total >= 0.01)
                    GROUP BY ym ORDER BY ym DESC;
                """, (issuer_id,))
                for m in months:
                    m["label"] = ym_to_label(m["ym"])
                month_totals = _get_month_totals(issuer_id, ym, "issued")
                base_extra.update({
                    "rows": rows,
                    "months": months,
                    "month_totals": month_totals,
                })
            else:
                # received y ppd usan los mismos datos (recibidas); PPD se filtra en front con metodo_pago
                rows = db_rows(f"""
                    SELECT uuid, fecha_emision, rfc_emisor, nombre_emisor, concepto, total, moneda,
                           COALESCE(impuestos, 0) AS impuestos, COALESCE(retenciones, 0) AS retenciones,
                           metodo_pago, status, xml_path
                    FROM sat_cfdi
                    WHERE issuer_id = ? AND direction = 'received' AND fecha_emision IS NOT NULL
                      AND {_ym_filt} AND total IS NOT NULL AND total >= 0.01
                      AND (tipo_comprobante IS NULL OR UPPER(TRIM(tipo_comprobante)) != 'N')
                      AND id IN (
                        SELECT id FROM (
                          SELECT id, ROW_NUMBER() OVER (
                            PARTITION BY issuer_id, direction, LOWER(TRIM(uuid))
                            ORDER BY id
                          ) AS rn
                          FROM sat_cfdi
                          WHERE issuer_id = ? AND direction = 'received' AND fecha_emision IS NOT NULL AND {_ym_filt} AND total IS NOT NULL AND total >= 0.01 AND (tipo_comprobante IS NULL OR UPPER(TRIM(tipo_comprobante)) != 'N')
                        ) WHERE rn = 1
                      )
                    ORDER BY fecha_emision DESC LIMIT {_row_limit};
                """, (issuer_id, ym, issuer_id, ym))
                months = db_rows("""
                    SELECT substr(fecha_emision,1,7) AS ym, count(*) AS n
                    FROM sat_cfdi
                    WHERE issuer_id = ? AND direction = 'received' AND fecha_emision IS NOT NULL
                      AND total IS NOT NULL AND total >= 0.01
                      AND (tipo_comprobante IS NULL OR UPPER(TRIM(tipo_comprobante)) != 'N')
                    GROUP BY ym ORDER BY ym DESC;
                """, (issuer_id,))
                for m in months:
                    m["label"] = ym_to_label(m["ym"])
                month_totals = _get_month_totals(issuer_id, ym, "received")
                base_extra.update({
                    "rows": rows,
                    "months": months,
                    "month_totals": month_totals,
                    "default_metodo_pago": "PPD" if tab == "ppd" else "",
                    "list_title": "Facturas recibidas (PPD)" if tab == "ppd" else "Facturas recibidas",
                })
            return _render_portal(
                request,
                issuer=issuer,
                template_name="portal_facturas.html",
                active_page="facturas_hub",
                title="Facturas",
                extra={
                    **base_extra,
                    "active_tab": tab,
                },
            )
        except Exception:
            logger.exception("portal: error renderizando /portal/facturas tab=%s", tab)
            raise

    @router.get("/invoices/nomina", response_class=HTMLResponse)
    def portal_invoices_nomina(request: Request, issuer: dict = Depends(get_portal_issuer), ym: str = None):
        try:
            issuer_id = issuer["id"]
            if not ym:
                ym = ym_now()
            ym = sanitize_ym(ym, ym_now())
            _ym_filt = ym_sql_filter(ym)
            _row_limit = 3000 if is_annual(ym) else 300
            rows = db_rows(f"""
                SELECT uuid, fecha_emision, rfc_emisor, nombre_emisor, total, moneda, status, xml_path,
                       serie, folio, concepto, forma_pago, metodo_pago, uso_cfdi, subtotal, descuento, impuestos,
                       tipo_comprobante, xml_status
                FROM sat_cfdi
                WHERE issuer_id = ? AND direction = 'received'
                  AND UPPER(TRIM(COALESCE(tipo_comprobante,''))) = 'N'
                  AND fecha_emision IS NOT NULL AND {_ym_filt}
                ORDER BY fecha_emision DESC LIMIT {_row_limit};
            """, (issuer_id, ym))
            months = db_rows("""
                SELECT substr(fecha_emision,1,7) AS ym, count(*) AS n
                FROM sat_cfdi
                WHERE issuer_id = ? AND direction = 'received'
                  AND UPPER(TRIM(COALESCE(tipo_comprobante,''))) = 'N'
                  AND fecha_emision IS NOT NULL
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
        except Exception:
            logger.exception("portal: error renderizando /portal/invoices/nomina ym=%s", ym)
            raise

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
            portal_error_type("file_missing", log_context={"issuer_id": issuer["id"], "uuid": u[:36]})
        uid, iid = _audit_user_issuer(request)
        if not subscription_service.can_issuer_use_sync_and_timbrado(issuer["id"], uid or 0):
            raise HTTPException(status_code=402, detail="Actualiza tu plan para descargar XML. Ve a /pricing.")
        audit.log(
            action="download_xml",
            user_id=uid,
            issuer_id=issuer["id"],
            details=u[:36],
            request=request,
            entity="cfdi",
            entity_id=u,
        )
        log_action(request, "download_xml", issuer_id=issuer["id"], entity_id=u[:36])
        file_access_log.log_file_access(
            request=request,
            action="download_xml",
            issuer_id=issuer["id"],
            user_id=uid,
            file_path=row.get("xml_path") if isinstance(row, dict) else None,
            entity="cfdi",
            entity_id=u[:36],
        )
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
            portal_error_type("file_missing", log_context={"issuer_id": issuer["id"], "uuid": uuid_clean[:36]})
        uid, _ = _audit_user_issuer(request)
        if not subscription_service.can_issuer_use_sync_and_timbrado(issuer["id"], uid or 0):
            raise HTTPException(status_code=402, detail="Actualiza tu plan para descargar PDF. Ve a /pricing.")
        audit.log(
            action="download_pdf",
            user_id=uid,
            issuer_id=issuer["id"],
            details=uuid_clean[:36],
            request=request,
            entity="cfdi",
            entity_id=uuid_clean,
        )
        log_action(request, "download_pdf", issuer_id=issuer["id"], entity_id=uuid_clean[:36])
        file_access_log.log_file_access(
            request=request,
            action="download_pdf",
            issuer_id=issuer["id"],
            user_id=uid,
            file_path=row.get("xml_path") if isinstance(row, dict) else None,
            entity="cfdi",
            entity_id=uuid_clean[:36],
        )
        try:
            from cfdi_pdf import build_pdf, parse_cfdi_xml
            data = parse_cfdi_xml(abs_path)
            pdf_bytes = build_pdf(data)
        except ImportError:
            portal_error_type("reportlab_missing", log_context={"issuer_id": issuer["id"], "uuid": uuid_clean[:36]})
        except Exception:
            logger.exception(
                "portal: error generando PDF issuer_id=%s uuid=%s",
                issuer["id"],
                uuid_clean[:36],
            )
            portal_error_type("server_error", log_context={"issuer_id": issuer["id"], "uuid": uuid_clean[:36]}, override_message="No se pudo generar el PDF. Intenta de nuevo.")
        if not pdf_bytes:
            portal_error_type("server_error", log_context={"issuer_id": issuer["id"]}, override_message="La generación del PDF devolvió vacío.")
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

    def _get_invoice_record(issuer_id: int, uuid: str) -> Optional[dict]:
        """Get local invoice record with cancel/replacement info."""
        u = (uuid or "").strip()
        if not u:
            return None
        conn = db()
        try:
            row = conn.execute(
                """SELECT id, facturapi_invoice_id, cancel_status, cancel_motive,
                          replacement_uuid, replaces_uuid, cancelled, cancelled_at
                   FROM invoices
                   WHERE issuer_id = ? AND LOWER(TRIM(uuid)) = LOWER(?)
                   LIMIT 1""",
                (issuer_id, u),
            ).fetchone()
        except Exception:
            return None
        finally:
            conn.close()
        return dict(row) if row else None

    @router.get("/cfdi/issued/{uuid}", response_class=HTMLResponse)
    def portal_cfdi_detail_issued(request: Request, uuid: str, issuer: dict = Depends(get_portal_issuer)):
        cfdi = _get_cfdi_by_uuid(issuer["id"], uuid, "issued")
        if not cfdi:
            return _render_portal(
                request,
                issuer=issuer,
                template_name="portal_cfdi_detail.html",
                active_page="issued",
                title="CFDI no encontrado",
                extra={"cfdi": None, "direction": "issued", "error": "not_found", "requested_uuid": uuid},
                status_code=404,
            )
        uid = getattr(request.state, "user_id", None) or 0
        audit.log(
            action="cfdi_view",
            user_id=uid if uid else None,
            issuer_id=issuer["id"],
            details=f"direction=issued uuid={(uuid or '')[:36]}",
            request=request,
            entity="cfdi",
            entity_id=(uuid or "").strip()[:36],
        )
        invoice_record = _get_invoice_record(issuer["id"], uuid)
        return _render_portal(
            request,
            issuer=issuer,
            template_name="portal_cfdi_detail.html",
            active_page="issued",
            title="Detalle CFDI emitido",
            extra={"cfdi": cfdi, "direction": "issued", "invoice_record": invoice_record},
        )

    @router.get("/cfdi/received/{uuid}", response_class=HTMLResponse)
    def portal_cfdi_detail_received(request: Request, uuid: str, issuer: dict = Depends(get_portal_issuer)):
        cfdi = _get_cfdi_by_uuid(issuer["id"], uuid, "received")
        if not cfdi:
            return _render_portal(
                request,
                issuer=issuer,
                template_name="portal_cfdi_detail.html",
                active_page="received",
                title="CFDI no encontrado",
                extra={"cfdi": None, "direction": "received", "error": "not_found", "requested_uuid": uuid},
                status_code=404,
            )
        uid = getattr(request.state, "user_id", None) or 0
        audit.log(
            action="cfdi_view",
            user_id=uid if uid else None,
            issuer_id=issuer["id"],
            details=f"direction=received uuid={(uuid or '')[:36]}",
            request=request,
            entity="cfdi",
            entity_id=(uuid or "").strip()[:36],
        )
        return _render_portal(
            request,
            issuer=issuer,
            template_name="portal_cfdi_detail.html",
            active_page="received",
            title="Detalle CFDI recibido",
            extra={"cfdi": cfdi, "direction": "received"},
        )

    @router.get("/facturas/export", response_class=Response)
    def portal_facturas_export(
        request: Request,
        issuer: dict = Depends(get_portal_issuer),
        tab: str = Query("issued"),
        ym: Optional[str] = Query(None),
    ):
        """Export facturas emitidas or recibidas to CSV."""
        issuer_id = int(issuer.get("id") or 0)
        if issuer_id <= 0:
            raise HTTPException(status_code=401, detail="Sesión inválida")
        if tab not in ("issued", "received"):
            tab = "issued"
        period = sanitize_ym(ym or "", ym_now())
        _ym_filt = ym_sql_filter(period)

        if tab == "issued":
            rows = db_rows(f"""
                SELECT uuid, fecha_emision, rfc_receptor, nombre_receptor, concepto,
                       COALESCE(total - COALESCE(impuestos,0), total) AS subtotal,
                       COALESCE(impuestos, 0) AS iva, total, status
                FROM sat_cfdi
                WHERE issuer_id = ? AND direction = 'issued' AND fecha_emision IS NOT NULL
                  AND {_ym_filt} AND (total IS NULL OR total >= 0.01)
                ORDER BY fecha_emision DESC
            """, (issuer_id, period)) or []
            headers = ["Fecha", "Receptor", "RFC", "Concepto", "Subtotal", "IVA", "Total", "UUID", "Estado"]
            def row_to_list(r):
                return [
                    (r.get("fecha_emision") or "")[:10],
                    r.get("nombre_receptor") or "",
                    r.get("rfc_receptor") or "",
                    r.get("concepto") or "",
                    r.get("subtotal") or 0,
                    r.get("iva") or 0,
                    r.get("total") or 0,
                    r.get("uuid") or "",
                    r.get("status") or "",
                ]
            fname = f"facturas_emitidas_{period}.csv"
        else:
            rows = db_rows(f"""
                SELECT uuid, fecha_emision, rfc_emisor, nombre_emisor, concepto,
                       COALESCE(total - COALESCE(impuestos,0), total) AS subtotal,
                       COALESCE(impuestos, 0) AS iva, total
                FROM sat_cfdi
                WHERE issuer_id = ? AND direction = 'received' AND fecha_emision IS NOT NULL
                  AND {_ym_filt} AND total IS NOT NULL AND total >= 0.01
                  AND (tipo_comprobante IS NULL OR UPPER(TRIM(tipo_comprobante)) != 'N')
                ORDER BY fecha_emision DESC
            """, (issuer_id, period)) or []
            headers = ["Fecha", "Emisor", "RFC", "Concepto", "Subtotal", "IVA", "Total", "UUID"]
            def row_to_list(r):
                return [
                    (r.get("fecha_emision") or "")[:10],
                    r.get("nombre_emisor") or "",
                    r.get("rfc_emisor") or "",
                    r.get("concepto") or "",
                    r.get("subtotal") or 0,
                    r.get("iva") or 0,
                    r.get("total") or 0,
                    r.get("uuid") or "",
                ]
            fname = f"facturas_recibidas_{period}.csv"

        import csv
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(headers)
        for r in rows:
            writer.writerow(row_to_list(r))
        csv_bytes = output.getvalue().encode("utf-8-sig")
        return Response(
            content=csv_bytes,
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{fname}"'},
        )

