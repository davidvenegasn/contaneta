# Rutas de facturación: submit del formulario y descargas (XML/PDF desde sat_cfdi o Facturapi)
import logging
import os
from typing import Optional, List

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Request, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse, Response, RedirectResponse

from fastapi import Request

from config import BASE_DIR
from database import db, table_exists, safe_update
from facturapi_client import create_invoice, download_invoice, FacturapiError
from validators import validate_customer
from services.form_parse import parse_items_from_form, parse_payments_from_form
from services import csrf as csrf_service, audit, subscription as subscription_service
from services.action_log import log_action
from services import invoices_service
from services import file_access_log
from routers.deps import get_portal_issuer


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
        try:
            form = await request.form()
            csrf_token = form.get("csrf_token") if isinstance(form.get("csrf_token"), str) else None
            token_val = (csrf_token or request.headers.get("X-CSRF-Token") or "").strip()
            if not csrf_service.verify_csrf_token(token_val):
                return HTMLResponse("<h3>Error</h3><p>Token de seguridad inválido o expirado. Recarga la página e intenta de nuevo.</p>", status_code=400)
            return _submit_impl(templates, request, issuer, form)
        except HTTPException:
            raise
        except FacturapiError as fe:
            return HTMLResponse(
                "<h3>Error al timbrar</h3><p>No pudimos completar la facturación. Revisa los datos e intenta de nuevo.</p>",
                status_code=400,
            )
        except Exception:
            logger.exception("invoicing submit: issuer_id=%s", issuer.get("id"))
            return HTMLResponse(
                "<h3>Error</h3><p>No pudimos completar la acción. Intenta de nuevo.</p>",
                status_code=500,
            )

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
            from cfdi_pdf import parse_cfdi_xml, build_pdf
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
            blob = download_invoice(issuer["facturapi_org_id"], invoice_id_clean, fmt)
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
    cur = conn.execute(
        """
        INSERT INTO invoices (
            issuer_id, currency, exchange_rate,
            payment_form, payment_method, cfdi_use,
            customer_rfc, customer_legal_name,
            customer_zip, customer_tax_system, customer_email
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            issuer["id"],
            currency.upper(),
            exchange,
            payment_form,
            payment_method,
            cfdi_use_val,
            customer_rfc.upper(),
            customer_legal_name,
            customer_zip,
            customer_tax_system,
            customer_email or None,
        ),
    )
    invoice_local_id = cur.lastrowid
    safe_update(
        conn,
        "invoices",
        invoice_local_id,
        {
            "export_code": export_code,
            "tipo_comprobante": tipo_comprobante,
            "series": serie or None,
            "folio_number": folio_number,
            "order_ref": order_ref or None,
            "issue_date": issue_date or None,
            "notes": notes or None,
        },
    )

    if items:
        for it in items:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(invoice_items)").fetchall()}
            base_cols = ["invoice_id", "quantity", "description", "product_key", "unit_price", "iva_rate"]
            base_vals = [
                invoice_local_id,
                it["quantity"],
                it["product"]["description"],
                it["product"]["product_key"],
                it["product"]["price"],
                it["product"]["taxes"][0]["rate"],
            ]
            extra = {}
            if "unit_key" in cols:
                extra["unit_key"] = it["product"].get("unit_key")
            if "discount" in cols:
                extra["discount"] = it.get("discount", 0.0)
            insert_cols = base_cols + list(extra.keys())
            insert_vals = base_vals + list(extra.values())
            placeholders = ", ".join(["?"] * len(insert_cols))
            col_sql = ", ".join(insert_cols)
            conn.execute(
                f"INSERT INTO invoice_items ({col_sql}) VALUES ({placeholders})",
                tuple(insert_vals),
            )
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
                print(f"[submit] save_customer failed: {e}")

    payload = invoices_service.build_invoice_payload(
        invoice_type=tipo_comprobante,
        export_code=export_code or "01",
        customer=invoices_service.build_customer(
            rfc=customer_rfc,
            legal_name=customer_legal_name,
            zip_code=customer_zip,
            tax_system=customer_tax_system,
            email=customer_email or None,
        ),
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
    )

    if issuer.get("facturapi_org_id") in (None, "", 0) or issuer.get("id") == -1:
        raise ValueError("DEV_MODE activo: token de prueba. Configura un token real/issuer para timbrar.")
    invoice = create_invoice(issuer["facturapi_org_id"], payload)
    fact_id = invoice.get("id")
    uuid = invoice.get("uuid")
    total = invoice.get("total")

    conn.execute(
        "UPDATE invoices SET facturapi_invoice_id = ?, uuid = ?, total = ? WHERE id = ? AND issuer_id = ?",
        (fact_id, uuid, total, invoice_local_id, issuer["id"]),
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
            print(f"[submit] storing payment_relations failed: {e}")
    conn.commit()
    conn.close()

    log_action(request, "invoice_created", issuer_id=issuer["id"], invoice_id=fact_id, uuid=(uuid or "")[:36])

    return templates.TemplateResponse(
        "success.html",
        {
            "request": request,
            "token": "",
            "facturapi_invoice_id": fact_id,
            "uuid": uuid,
            "total": total,
            "issuer_alias": issuer.get("alias") or issuer.get("legal_name") or "ContaNeta",
            "issuer_rfc": issuer.get("rfc") or "",
        },
    )
