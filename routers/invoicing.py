# Rutas de facturación: submit del formulario y descargas (XML/PDF desde sat_cfdi o Facturapi)
import logging
import os

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from config import BASE_DIR
from database import db, table_exists
from facturapi_client import FacturapiError, create_invoice, download_invoice
from routers.deps import get_portal_issuer
from services import audit, file_access_log
from services.action_log import log_action
from services.auth import csrf as csrf_service
from services.billing import subscription as subscription_service
from services.form_parse import parse_items_from_form, parse_payments_from_form
from services.invoices import invoices_engine
from validators import validate_customer


def _safe_abs_path(path_like: str) -> str:
    """Resuelve ruta guardada a ruta absoluta bajo BASE_DIR (evita path traversal)."""
    if not path_like:
        raise ValueError("XML no disponible")
    path_like = (path_like or "").strip()
    if not path_like:
        raise ValueError("XML no disponible")
    p = path_like if os.path.isabs(path_like) else os.path.join(BASE_DIR, path_like)
    abs_p = os.path.normpath(os.path.abspath(p))
    base = os.path.abspath(BASE_DIR)
    if not abs_p.startswith(base + os.sep):
        raise ValueError("Ruta XML inválida")
    # Guardrail: nunca servir llaves/certs ni credenciales aunque alguien logre inyectar un path.
    blocked = [
        os.path.join(base, "keys"),
        os.path.join(base, "storage", "credentials"),
    ]
    for b in blocked:
        b_abs = os.path.normpath(os.path.abspath(b))
        if abs_p == b_abs or abs_p.startswith(b_abs + os.sep):
            raise ValueError("Ruta XML inválida")
    return abs_p


def get_invoicing_router(templates):
    """Router con POST /submit y GET /download/xml|pdf|{fmt}/{invoice_id}."""
    router = APIRouter(tags=["invoicing"])

    @router.post("/submit", response_class=HTMLResponse)
    async def submit(
        request: Request,
        issuer: dict = Depends(get_portal_issuer),
        customer_rfc: str = Form(...),
        customer_legal_name: str = Form(...),
        customer_zip: str = Form(...),
        customer_tax_system: str = Form(...),
        cfdi_use: str = Form(...),
        customer_email: str = Form(""),
        currency: str = Form("MXN"),
        exchange_rate: str = Form(""),
        payment_method: str = Form("PUE"),
        payment_form: str = Form(...),
        receiver_is_pm: str = Form(""),
        issuer_tax_system: str = Form(""),
    ):
        # Detect whether the caller wants JSON (sleek in-portal modal) or HTML
        # (fallback for non-JS submits). Either way, the error is shown INSIDE
        # the portal layout — never as a bare HTML page.
        wants_json = "application/json" in (request.headers.get("Accept") or "").lower()

        def _err_response(status: int, title: str, message: str, extra: dict | None = None):
            from fastapi.responses import JSONResponse
            if wants_json:
                body = {"ok": False, "error": {"title": title, "message": message}}
                if extra:
                    body["error"].update(extra)
                return JSONResponse(status_code=status, content=body)
            # HTML fallback: render inside portal layout (never bare h3+p).
            try:
                from routers.portal._helpers import render_portal
                return render_portal(
                    templates,
                    request,
                    issuer=issuer,
                    template_name="components/portal_error_inline.html",
                    active_page=None,
                    title=title,
                    error_title=title,
                    error_message=message,
                    back_url="/portal/create",
                    back_label="Volver a nueva factura",
                    status_code=status,
                )
            except Exception:
                # Last-resort fallback if template render fails; still inside portal styles.
                return HTMLResponse(
                    f'<!doctype html><html><head><link rel="stylesheet" href="/static/css/portal.css">'
                    f'<title>{title}</title></head><body class="portal" style="padding:40px;">'
                    f'<div class="card" style="max-width:520px;margin:auto;padding:24px;">'
                    f'<h3 style="margin:0 0 8px;">{title}</h3>'
                    f'<p style="color:var(--muted);margin:0 0 16px;">{message}</p>'
                    f'<a href="/portal/create" class="btn-primary" style="text-decoration:none;">Volver</a>'
                    f'</div></body></html>',
                    status_code=status,
                )

        try:
            form = await request.form()
            csrf_token = form.get("csrf_token") if isinstance(form.get("csrf_token"), str) else None
            token_val = (csrf_token or request.headers.get("X-CSRF-Token") or "").strip()
            if not csrf_service.verify_csrf_token(token_val):
                return _err_response(400, "Sesión expirada",
                                     "Tu token de seguridad expiró. Recarga la página e intenta de nuevo.")
            return _submit_impl(templates, request, issuer, form)
        except HTTPException:
            raise
        except FacturapiError as fe:
            logger.warning("FacturapiError: issuer_id=%s %s", issuer.get("id"), fe)
            # Try to surface Facturapi's actual message — much more actionable than a generic one.
            import re, json as _json
            raw = str(fe)
            facturapi_message = "No pudimos completar la facturación. Revisa los datos e intenta de nuevo."
            m = re.search(r"\{.*\}", raw)
            if m:
                try:
                    parsed = _json.loads(m.group(0))
                    facturapi_message = parsed.get("message") or facturapi_message
                except Exception:
                    pass
            return _err_response(502, "Error al timbrar", facturapi_message,
                                 extra={"source": "facturapi"})
        except ValueError as ve:
            return _err_response(400, "Datos incompletos", str(ve))
        except Exception as e:
            logger.exception("invoicing submit: issuer_id=%s", issuer.get("id"))
            return _err_response(500, "Error inesperado",
                                 "No pudimos completar la acción. Intenta de nuevo en unos segundos.")

    def _fallback_download_from_facturapi(issuer: dict, uuid_clean: str, fmt: str) -> bytes | None:
        """When sat_cfdi has no local XML (e.g. fresh TEST emission, no SAT sync
        yet), look up the CFDI by uuid in the local invoices table and pull the
        file directly from Facturapi using its facturapi_invoice_id.
        Returns the file bytes on success, None if no Facturapi reference exists.
        """
        if not issuer.get("facturapi_org_id"):
            return None
        conn = db()
        try:
            row = conn.execute(
                "SELECT facturapi_invoice_id FROM invoices WHERE issuer_id = ? AND LOWER(TRIM(uuid)) = LOWER(?) AND facturapi_invoice_id IS NOT NULL AND facturapi_invoice_id != '' LIMIT 1",
                (issuer["id"], uuid_clean),
            ).fetchone()
        finally:
            conn.close()
        if not row:
            return None
        fact_id = row["facturapi_invoice_id"] if hasattr(row, "keys") else row[0]
        try:
            return download_invoice(issuer["id"], issuer["facturapi_org_id"], fact_id, fmt)
        except FacturapiError:
            logger.exception("Facturapi download fallback failed: uuid=%s fmt=%s", uuid_clean[:36], fmt)
            return None

    @router.get("/download/xml/{uuid}")
    def download_xml(request: Request, uuid: str, issuer: dict = Depends(get_portal_issuer)):
        uuid_clean = (uuid or "").strip().split()[0] if uuid else ""
        if not uuid_clean:
            raise HTTPException(status_code=404, detail="UUID no válido")
        try:
            conn = db()
            row = conn.execute(
                "SELECT xml_path, uuid FROM sat_cfdi WHERE issuer_id = ? AND LOWER(TRIM(uuid)) = LOWER(?) LIMIT 1",
                (issuer["id"], uuid_clean),
            ).fetchone()
            conn.close()
            if not row or not row["xml_path"]:
                # Fallback: not yet in local sat_cfdi (e.g. test emission, sync didn't run).
                # Pull XML directly from Facturapi using the invoice's facturapi_invoice_id.
                blob = _fallback_download_from_facturapi(issuer, uuid_clean, "xml")
                if blob:
                    return Response(
                        content=blob,
                        media_type="application/xml",
                        headers={"Content-Disposition": f'attachment; filename="{uuid_clean}.xml"'},
                    )
                raise HTTPException(status_code=404, detail="XML no encontrado para este UUID")
            abs_path = _safe_abs_path(row["xml_path"])
            if not os.path.exists(abs_path):
                raise HTTPException(status_code=404, detail="Archivo XML no existe en disco")
            audit.log(
                action="download_xml",
                user_id=getattr(request.state, "user_id", None),
                issuer_id=issuer["id"],
                details=f"uuid={uuid_clean[:36]}",
                request=request,
                entity="cfdi",
                entity_id=uuid_clean,
            )
            log_action(request, "download_xml", issuer_id=issuer["id"], entity_id=uuid_clean[:36])
            file_access_log.log_file_access(
                request=request,
                action="download_xml",
                issuer_id=issuer["id"],
                user_id=getattr(request.state, "user_id", None),
                file_path=(row.get("xml_path") if isinstance(row, dict) else None),
                entity="cfdi",
                entity_id=uuid_clean[:36],
            )
            with open(abs_path, "rb") as f:
                xml_bytes = f.read()
            return Response(
                content=xml_bytes,
                media_type="application/xml",
                headers={"Content-Disposition": f'attachment; filename="{row["uuid"]}.xml"'},
            )
        except HTTPException:
            raise
        except ValueError:
            logger.exception("download_xml: uuid=%s issuer_id=%s", uuid_clean[:36], issuer.get("id"))
            raise HTTPException(status_code=404, detail="Recurso no encontrado")

    @router.get("/download/pdf/{uuid}")
    def download_pdf(request: Request, uuid: str, issuer: dict = Depends(get_portal_issuer), dl: int = 0):
        uuid_clean = (uuid or "").strip().split()[0] if uuid else ""
        if not uuid_clean:
            raise HTTPException(status_code=404, detail="UUID no válido")
        try:
            conn = db()
            row = conn.execute(
                "SELECT xml_path, uuid FROM sat_cfdi WHERE issuer_id = ? AND LOWER(TRIM(uuid)) = LOWER(?) LIMIT 1",
                (issuer["id"], uuid_clean),
            ).fetchone()
            conn.close()
            if not row or not row["xml_path"]:
                # Fallback: pull PDF directly from Facturapi when local sat_cfdi
                # is not yet populated (e.g. fresh emission in TEST sandbox).
                blob = _fallback_download_from_facturapi(issuer, uuid_clean, "pdf")
                if blob:
                    disposition = "attachment" if dl else "inline"
                    filename = f"cfdi-{uuid_clean[:8]}.pdf"
                    return Response(
                        content=blob,
                        media_type="application/pdf",
                        headers={"Content-Disposition": f'{disposition}; filename="{filename}"'},
                    )
                raise HTTPException(status_code=404, detail="XML no encontrado; no se puede generar PDF")
            abs_path = _safe_abs_path(row["xml_path"])
            if not os.path.exists(abs_path):
                raise HTTPException(status_code=404, detail="Archivo XML no existe en disco")
            audit.log(
                action="download_pdf",
                user_id=getattr(request.state, "user_id", None),
                issuer_id=issuer["id"],
                details=f"uuid={uuid_clean[:36]}",
                request=request,
                entity="cfdi",
                entity_id=uuid_clean,
            )
            log_action(request, "download_pdf", issuer_id=issuer["id"], entity_id=uuid_clean[:36])
            file_access_log.log_file_access(
                request=request,
                action="download_pdf",
                issuer_id=issuer["id"],
                user_id=getattr(request.state, "user_id", None),
                file_path=(row.get("xml_path") if isinstance(row, dict) else None),
                entity="cfdi",
                entity_id=uuid_clean[:36],
            )
            from cfdi_pdf import build_pdf, parse_cfdi_xml
            data = parse_cfdi_xml(abs_path)
            pdf_bytes = build_pdf(data)
            if not pdf_bytes:
                raise HTTPException(status_code=500, detail="Error al generar PDF")
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
        except HTTPException:
            raise
        except ValueError:
            logger.exception("download_pdf: uuid=%s issuer_id=%s", uuid_clean[:36], issuer.get("id"))
            raise HTTPException(status_code=404, detail="Recurso no encontrado")

    @router.get("/download/{fmt}/{invoice_id}")
    def download_fmt(
        request: Request,
        fmt: str,
        invoice_id: str,
        issuer: dict = Depends(get_portal_issuer),
    ):
        fmt = fmt.lower()
        if fmt not in ("pdf", "xml", "zip"):
            return HTMLResponse("Formato inválido", status_code=400)
        invoice_id_clean = (invoice_id or "").strip()
        if not invoice_id_clean:
            raise HTTPException(status_code=404, detail="Identificador de factura no válido")
        try:
            if issuer.get("facturapi_org_id") in (None, "", 0) or issuer.get("id") == -1:
                raise ValueError("DEV_MODE activo: no hay issuer real para descargar. Usa token real.")
            conn = db()
            row = conn.execute(
                "SELECT 1 FROM invoices WHERE issuer_id = ? AND facturapi_invoice_id = ? LIMIT 1",
                (issuer["id"], invoice_id_clean),
            ).fetchone()
            conn.close()
            if not row:
                audit.log(
                    action="facturapi_download_tenant_denied",
                    user_id=getattr(request.state, "user_id", None),
                    issuer_id=issuer["id"],
                    details=f"fmt={fmt} invoice_id={invoice_id_clean[:64]}",
                    request=request,
                    entity="invoices",
                    entity_id=invoice_id_clean,
                )
                raise HTTPException(status_code=404, detail="Factura no encontrada")
            blob = download_invoice(issuer["id"], issuer["facturapi_org_id"], invoice_id_clean, fmt)
            file_access_log.log_file_access(
                request=request,
                action=f"download_facturapi_{fmt}",
                issuer_id=issuer["id"],
                user_id=getattr(request.state, "user_id", None),
                file_path=None,
                entity="invoices",
                entity_id=invoice_id_clean[:64],
            )
            media = {"pdf": "application/pdf", "xml": "application/xml", "zip": "application/zip"}[fmt]
            filename = f"invoice_{invoice_id_clean}.{fmt}"
            return Response(
                content=blob,
                media_type=media,
                headers={"Content-Disposition": f'attachment; filename="{filename}"'},
            )
        except HTTPException:
            raise
        except Exception:
            logger.exception("invoicing download_fmt: issuer_id=%s fmt=%s invoice_id=%s", issuer.get("id"), fmt, invoice_id)
            return HTMLResponse(
                "No pudimos completar la descarga. Intenta de nuevo.",
                status_code=500,
            )

    return router


def _submit_impl(templates, request: Request, issuer: dict, form):
    user_id = getattr(request.state, "user_id", 0) or 0
    if not subscription_service.can_issuer_use_sync_and_timbrado(issuer.get("id"), user_id):
        return RedirectResponse(url="/pricing?reason=trial_expired", status_code=302)
    export_code = (form.get("exportacion") or "01").strip()
    tipo_comprobante = (form.get("tipo_comprobante") or "I").strip().upper()
    payments_payload = None
    items = None
    if tipo_comprobante == "P":
        payments_payload = parse_payments_from_form(form)
    else:
        items = parse_items_from_form(form)

    serie = (form.get("serie") or "").strip()
    folio = (form.get("folio") or "").strip()
    order_ref = (form.get("order_ref") or "").strip()
    issue_date = (form.get("issue_date") or "").strip()
    notes = (form.get("notes") or "").strip()
    save_customer = (form.get("save_customer") or "").strip() == "1"
    customer_alias = (form.get("customer_alias") or "").strip()
    customer_rfc = (form.get("customer_rfc") or "").strip()
    customer_legal_name = (form.get("customer_legal_name") or "").strip()
    customer_zip = (form.get("customer_zip") or "").strip()
    customer_tax_system = (form.get("customer_tax_system") or "").strip()
    cfdi_use_val = (form.get("cfdi_use") or "").strip().upper()
    customer_email = (form.get("customer_email") or "").strip()
    currency = (form.get("currency") or "MXN").strip()
    exchange_rate = (form.get("exchange_rate") or "").strip()
    payment_method = (form.get("payment_method") or "PUE").strip().upper()
    payment_form = (form.get("payment_form") or "").strip()

    if tipo_comprobante == "P":
        cfdi_use_val = "P01"

    folio_number = None
    if folio:
        try:
            folio_number = int(folio)
        except Exception:
            raise ValueError("Folio inválido. Debe ser numérico.")
    if tipo_comprobante not in ("I", "E", "P", "T", "N"):
        raise ValueError("Tipo de comprobante inválido.")

    exchange = None
    if currency.upper() == "USD":
        if not exchange_rate:
            raise ValueError("Captura tipo de cambio para USD.")
        exchange = float(exchange_rate)

    conn = db()
    invoice_local_id = invoices_engine.save_invoice_record(
        conn, issuer["id"],
        currency=currency.upper(), exchange_rate=exchange,
        payment_form=payment_form, payment_method=payment_method, cfdi_use=cfdi_use_val,
        customer_rfc=customer_rfc.upper(), customer_legal_name=customer_legal_name,
        customer_zip=customer_zip, customer_tax_system=customer_tax_system,
        customer_email=customer_email or None, export_code=export_code,
        tipo_comprobante=tipo_comprobante, series=serie or None,
        folio_number=folio_number, order_ref=order_ref or None,
        issue_date=issue_date or None, notes=notes or None,
    )
    if items:
        invoices_engine.save_invoice_items(conn, invoice_local_id, items)
    conn.commit()

    if save_customer:
        errs = validate_customer(
            customer_rfc.upper(),
            customer_legal_name,
            customer_zip,
            customer_tax_system,
            customer_email or None,
        )
        if not errs:
            try:
                conn.execute(
                    """
                    INSERT INTO customer_profiles (
                        issuer_id, rfc, legal_name, zip, tax_system, email, alias, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(issuer_id, rfc) DO UPDATE SET
                        legal_name = excluded.legal_name,
                        zip = excluded.zip,
                        tax_system = excluded.tax_system,
                        email = excluded.email,
                        alias = excluded.alias,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (
                        issuer["id"],
                        customer_rfc.upper(),
                        customer_legal_name,
                        customer_zip,
                        customer_tax_system,
                        customer_email or None,
                        customer_alias or None,
                    ),
                )
                conn.commit()
            except Exception as e:
                logger.warning("save_customer failed: %s", e)

    payload = invoices_engine.build_facturapi_payload(
        invoice_type=tipo_comprobante,
        export_code=export_code or "01",
        customer={
            "rfc": customer_rfc,
            "legal_name": customer_legal_name,
            "zip": customer_zip,
            "tax_system": customer_tax_system,
            "email": customer_email or None,
        },
        items=items if items is not None else None,
        payments=payments_payload if payments_payload is not None else None,
        cfdi_use=cfdi_use_val,
        payment_form=payment_form,
        payment_method=payment_method,
        currency=currency.upper(),
        series=serie or None,
        folio_number=folio_number,
        issue_date=issue_date or None,
        order_ref=order_ref or None,
        notes=notes or None,
        exchange=exchange,
        validate_receiver=(tipo_comprobante != "P"),
    )

    # Receptor-type aware tweaks: inject `global` block for "Público en general" sales.
    # Facturapi expects the field literally named `global` (verified empirically).
    receptor_type = (form.get("receptor_type") or "normal").strip()
    if receptor_type == "publico_general" and customer_rfc.upper() == "XAXX010101000":
        try:
            year_int = int((form.get("global_year") or "2026").strip())
        except (TypeError, ValueError):
            year_int = 2026
        # Periodicity comes as SAT numeric code (01..05). Map to Facturapi's
        # accepted vocabulary if it requires words; otherwise pass numeric.
        SAT_PERIODICITY = {
            "01": "day", "02": "week", "03": "fortnight",
            "04": "month", "05": "two_months",
        }
        per_raw = (form.get("global_periodicity") or "04").strip()
        per_value = SAT_PERIODICITY.get(per_raw, per_raw)
        payload["global"] = {
            "periodicity": per_value,
            "months": (form.get("global_month") or "01").strip(),
            "year": year_int,
        }

    if issuer.get("facturapi_org_id") in (None, "", 0) or issuer.get("id") == -1:
        raise ValueError("DEV_MODE activo: token de prueba. Configura un token real/issuer para timbrar.")
    invoice = create_invoice(issuer["id"], issuer["facturapi_org_id"], payload)
    fact_id = invoice.get("id")
    uuid = invoice.get("uuid")
    total = invoice.get("total")

    invoices_engine.update_invoice_stamp(
        conn, invoice_local_id, issuer["id"],
        facturapi_id=fact_id, uuid=uuid, total=total,
    )
    # Mirror to sat_cfdi so it shows up immediately in /portal/issued
    # without waiting for the next SAT sync cron.
    if uuid:
        invoices_engine.mirror_emitted_to_sat_cfdi(
            conn, issuer["id"],
            uuid=uuid,
            issuer_rfc=issuer.get("rfc") or "",
            issuer_legal_name=issuer.get("alias") or issuer.get("legal_name") or "",
            customer_rfc=customer_rfc.upper(),
            customer_legal_name=customer_legal_name,
            total=total,
            currency=currency.upper(),
            tipo_comprobante=tipo_comprobante,
            series=serie or None,
            folio_number=folio_number,
            payment_form=payment_form,
            payment_method=payment_method,
            cfdi_use=cfdi_use_val,
            issue_date=issue_date or None,
        )
    if tipo_comprobante == "P" and payments_payload and table_exists(conn, "payment_relations"):
        try:
            for p in payments_payload:
                for rd in p.get("related_documents", []):
                    r_uuid = (rd.get("uuid") or "").strip()
                    r_amt = float(rd.get("amount") or 0)
                    if not r_uuid or r_amt <= 0:
                        continue
                    rel = conn.execute(
                        "SELECT id FROM invoices WHERE issuer_id = ? AND uuid = ? LIMIT 1",
                        (issuer["id"], r_uuid),
                    ).fetchone()
                    related_local_id = int(rel["id"]) if rel else None
                    if related_local_id:
                        conn.execute(
                            """
                            INSERT INTO payment_relations (payment_invoice_id, related_invoice_id, related_uuid, amount)
                            VALUES (?, ?, ?, ?)
                            """,
                            (invoice_local_id, related_local_id, r_uuid, r_amt),
                        )
            conn.commit()
        except Exception as e:
            logger.warning("storing payment_relations failed: %s", e)
    conn.commit()
    conn.close()

    log_action(request, "invoice_created", issuer_id=issuer["id"], invoice_id=fact_id, uuid=(uuid or "")[:36])

    return templates.TemplateResponse(
        request,
        "success.html",
        {
            "token": "",
            "facturapi_invoice_id": fact_id,
            "uuid": uuid,
            "total": total,
            "issuer_alias": issuer.get("alias") or issuer.get("legal_name") or "ContaNeta",
            "issuer_rfc": issuer.get("rfc") or "",
        },
    )
