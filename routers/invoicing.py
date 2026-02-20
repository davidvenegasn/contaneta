# Rutas de facturación: submit del formulario y descargas (XML/PDF desde sat_cfdi o Facturapi)
import os
from typing import Optional, List

from fastapi import APIRouter, Request, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse, Response

from config import BASE_DIR
from database import db, table_exists, safe_update
from facturapi_client import create_invoice, download_invoice, FacturapiError
from validators import validate_customer
from services.form_parse import parse_items_from_form, parse_payments_from_form
from routers.deps import get_portal_issuer
from services import csrf as csrf_service


def _safe_abs_path(path_like: str) -> str:
    """Resuelve ruta guardada a ruta absoluta bajo BASE_DIR (evita path traversal)."""
    if not path_like:
        raise ValueError("XML no disponible")
    p = path_like if os.path.isabs(path_like) else os.path.join(BASE_DIR, path_like)
    abs_p = os.path.abspath(p)
    base = os.path.abspath(BASE_DIR)
    if not abs_p.startswith(base + os.sep):
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
            if not csrf_service.verify_csrf_token(csrf_token):
                return HTMLResponse("<h3>Error</h3><p>Token de seguridad inválido o expirado. Recarga la página e intenta de nuevo.</p>", status_code=400)
            return _submit_impl(templates, request, issuer, form)
        except FacturapiError as fe:
            return HTMLResponse(f"<h3>Error Facturapi</h3><p>{str(fe)}</p>", status_code=400)
        except Exception as e:
            return HTMLResponse(f"<h3>Error</h3><p>{str(e)}</p>", status_code=400)

    @router.get("/download/xml/{uuid}")
    def download_xml(uuid: str, issuer: dict = Depends(get_portal_issuer)):
        try:
            conn = db()
            row = conn.execute(
                "SELECT xml_path, uuid FROM sat_cfdi WHERE issuer_id = ? AND uuid = ? LIMIT 1",
                (issuer["id"], (uuid or "").strip()),
            ).fetchone()
            conn.close()
            if not row or not row["xml_path"]:
                raise HTTPException(status_code=404, detail="XML no encontrado para este UUID")
            abs_path = _safe_abs_path(row["xml_path"])
            if not os.path.exists(abs_path):
                raise HTTPException(status_code=404, detail="Archivo XML no existe en disco")
            with open(abs_path, "rb") as f:
                xml_bytes = f.read()
            return Response(
                content=xml_bytes,
                media_type="application/xml",
                headers={"Content-Disposition": f'attachment; filename="{row["uuid"]}.xml"'},
            )
        except HTTPException:
            raise
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))

    @router.get("/download/pdf/{uuid}")
    def download_pdf(uuid: str, issuer: dict = Depends(get_portal_issuer), dl: int = 0):
        try:
            uuid_clean = (uuid or "").strip().split()[0] if uuid else ""
            if not uuid_clean:
                raise HTTPException(status_code=404, detail="UUID no válido")
            conn = db()
            row = conn.execute(
                "SELECT xml_path, uuid FROM sat_cfdi WHERE issuer_id = ? AND uuid = ? LIMIT 1",
                (issuer["id"], uuid_clean),
            ).fetchone()
            conn.close()
            if not row or not row["xml_path"]:
                raise HTTPException(status_code=404, detail="XML no encontrado; no se puede generar PDF")
            abs_path = _safe_abs_path(row["xml_path"])
            if not os.path.exists(abs_path):
                raise HTTPException(status_code=404, detail="Archivo XML no existe en disco")
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
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))

    @router.get("/download/{fmt}/{invoice_id}")
    def download_fmt(fmt: str, invoice_id: str, issuer: dict = Depends(get_portal_issuer)):
        fmt = fmt.lower()
        if fmt not in ("pdf", "xml", "zip"):
            return HTMLResponse("Formato inválido", status_code=400)
        try:
            if issuer.get("facturapi_org_id") in (None, "", 0) or issuer.get("id") == -1:
                raise ValueError("DEV_MODE activo: no hay issuer real para descargar. Usa token real.")
            blob = download_invoice(issuer["facturapi_org_id"], invoice_id, fmt)
            media = {"pdf": "application/pdf", "xml": "application/xml", "zip": "application/zip"}[fmt]
            filename = f"invoice_{invoice_id}.{fmt}"
            return Response(
                content=blob,
                media_type=media,
                headers={"Content-Disposition": f'attachment; filename="{filename}"'},
            )
        except Exception as e:
            return HTMLResponse(f"Error descargando: {str(e)}", status_code=400)

    return router


def _submit_impl(templates, request: Request, issuer: dict, form):
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

    payload = {
        "type": tipo_comprobante,
        "export": export_code or "01",
        "customer": {
            "legal_name": customer_legal_name,
            "email": customer_email or None,
            "tax_id": customer_rfc.upper(),
            "tax_system": customer_tax_system,
            "address": {"zip": customer_zip},
        },
        **({"items": items} if items is not None else {}),
        **({"payments": payments_payload} if payments_payload is not None else {}),
        "use": cfdi_use_val,
        "payment_form": payment_form,
        "payment_method": payment_method,
        "currency": currency.upper(),
    }
    if serie:
        payload["series"] = serie
    if folio_number is not None:
        payload["folio_number"] = folio_number
    if issue_date:
        payload["date"] = issue_date
    if order_ref:
        payload["external_id"] = order_ref
    if notes:
        payload["conditions"] = notes
    if exchange is not None:
        payload["exchange"] = exchange

    if issuer.get("facturapi_org_id") in (None, "", 0) or issuer.get("id") == -1:
        raise ValueError("DEV_MODE activo: token de prueba. Configura un token real/issuer para timbrar.")
    invoice = create_invoice(issuer["facturapi_org_id"], payload)
    fact_id = invoice.get("id")
    uuid = invoice.get("uuid")
    total = invoice.get("total")

    conn.execute(
        "UPDATE invoices SET facturapi_invoice_id = ?, uuid = ?, total = ? WHERE id = ?",
        (fact_id, uuid, total, invoice_local_id),
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

    return templates.TemplateResponse(
        "success.html",
        {
            "request": request,
            "token": "",
            "facturapi_invoice_id": fact_id,
            "uuid": uuid,
            "total": total,
        },
    )
