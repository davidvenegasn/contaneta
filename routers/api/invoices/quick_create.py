"""Quick invoice creation and bulk issue routes."""
import logging

from fastapi import Body, Depends, HTTPException, Request

from database import db, db_rows
from routers.api._helpers import _api_rate_check
from routers.api.invoices._post_hooks import process_replacement_cancel, save_xml_and_register_cfdi
from routers.api.invoices._quick_create_helpers import (
    build_invoice_items,
    parse_rate,
    resolve_product,
)
from routers.deps import get_portal_issuer
from validators import validate_customer

logger = logging.getLogger(__name__)

from facturapi_client import FacturapiError, create_invoice
from services.action_log import log_action
from services.auth import csrf as csrf_service
from services.billing import subscription as subscription_service
from services.http import ok
from services.invoices import invoices_engine
from services.invoices.preflight import validate_can_issue_invoice


def register_invoices_quick_routes(router):
    """Register quick invoice creation and bulk issue routes."""

    @router.post("/invoices/quick")
    def api_invoices_quick(
        request: Request,
        payload: dict = Body(...),
        issuer: dict = Depends(get_portal_issuer),
    ):
        """Crea y timbra una factura con un solo concepto desde cliente + producto.

        Permite overrides minimos (receptor, concepto, IVA/retenciones) para el precalculo editable en Home.
        """
        csrf_service.verify_api_csrf(request)
        _api_rate_check(request, "api_invoice", max_attempts=20, window=60.0)
        user_id = getattr(request.state, "user_id", 0) or 0
        if not subscription_service.can_issuer_use_sync_and_timbrado(issuer.get("id"), user_id):
            raise HTTPException(status_code=402, detail="Actualiza tu plan para emitir facturas.")
        # Pre-flight checks
        preflight = validate_can_issue_invoice(issuer.get("id"), user_id)
        if not preflight["ok"]:
            first = preflight["errors"][0]
            raise HTTPException(status_code=400, detail=f"{first['message']} {first['action']}")
        customer_id = payload.get("customer_id")
        items_in = payload.get("items")
        product_id = payload.get("product_id")
        has_items = isinstance(items_in, list) and len(items_in) > 0
        if not customer_id:
            raise HTTPException(status_code=400, detail="customer_id es requerido.")
        if not has_items and not product_id:
            raise HTTPException(status_code=400, detail="product_id es requerido (o envia items).")
        try:
            customer_id = int(customer_id)
            if not has_items:
                product_id = int(product_id)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="customer_id/product_id invalidos.")

        # Single-item mode legacy fields
        quantity = None
        unit_price_override = None
        if not has_items:
            quantity = float(payload.get("quantity", 1))
            if quantity <= 0 or quantity > 999999:
                raise HTTPException(status_code=400, detail="Cantidad invalida.")
            unit_price_override = payload.get("unit_price")
            if unit_price_override is not None:
                try:
                    unit_price_override = float(unit_price_override)
                    if unit_price_override < 0:
                        raise HTTPException(status_code=400, detail="Precio unitario no puede ser negativo.")
                except (TypeError, ValueError):
                    raise HTTPException(status_code=400, detail="Precio unitario invalido.")

        issuer_id = issuer["id"]
        cust = db_rows(
            "SELECT id, rfc, legal_name, zip, tax_system, email FROM customer_profiles WHERE issuer_id = ? AND id = ? LIMIT 1",
            (issuer_id, customer_id),
        )
        if not cust:
            raise HTTPException(status_code=404, detail="Cliente no encontrado.")
        c = cust[0]

        # ----- Overrides (desde Home precalculo editable) -----
        customer_rfc = (c.get("rfc") or "").strip().upper()
        customer_legal_name = (
            (payload.get("customer_legal_name") or payload.get("customer_name") or c.get("legal_name") or "").strip()
            or (c.get("legal_name") or "").strip()
        )
        customer_zip = (payload.get("customer_zip") if payload.get("customer_zip") is not None else (c.get("zip") or "")).strip() or "00000"
        customer_tax_system = (payload.get("customer_tax_system") if payload.get("customer_tax_system") is not None else (c.get("tax_system") or "")).strip() or "616"
        customer_email_raw = (payload.get("customer_email") if payload.get("customer_email") is not None else (c.get("email") or "")).strip()
        customer_email = customer_email_raw or None

        isr_ret_rate = parse_rate(payload, "isr_ret_rate", 0.0)
        iva_ret_rate = parse_rate(payload, "iva_ret_rate", 0.0)

        cfdi_use = (payload.get("cfdi_use") or payload.get("uso_cfdi") or "G03").strip().upper() or "G03"
        payment_form = (payload.get("payment_form") or "03").strip() or "03"
        payment_method = (payload.get("payment_method") or "PUE").strip().upper() or "PUE"
        currency = (payload.get("currency") or "MXN").strip().upper() or "MXN"

        items_fact, items_meta = build_invoice_items(
            issuer_id, payload, items_in, product_id,
            quantity, unit_price_override, isr_ret_rate, iva_ret_rate,
        )

        replaces_uuid = (payload.get("replaces_uuid") or "").strip() or None
        related_docs = None
        if replaces_uuid:
            related_docs = [{"relationship": "04", "documents": [replaces_uuid]}]

        payload_fact = invoices_engine.build_facturapi_payload(
            invoice_type="I",
            export_code="01",
            customer={
                "rfc": customer_rfc,
                "legal_name": customer_legal_name,
                "zip": customer_zip,
                "tax_system": customer_tax_system,
                "email": customer_email,
            },
            items=items_fact,
            related_documents=related_docs,
            cfdi_use=cfdi_use,
            payment_form=payment_form,
            payment_method=payment_method,
            currency=currency,
            validate_receiver=True,
        )
        # Validate against Lista 69-B before stamping (skip generic RFCs)
        if customer_rfc and customer_rfc not in ("XAXX010101000", "XEXX010101000"):
            from services.sat.lista_69b import check_rfc_69b
            rfc_69b = check_rfc_69b(customer_rfc)
            if rfc_69b:
                sit = (rfc_69b.get("situacion") or "").lower()
                if sit in ("definitivo", "sentencia favorable"):
                    log_action(request, "stamp_blocked_69b",
                               issuer_id=issuer_id, customer_rfc=customer_rfc,
                               situacion=rfc_69b.get("situacion"))
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            f"El RFC {customer_rfc} está en la Lista 69-B del SAT como "
                            f"'{rfc_69b['situacion']}'. No se puede emitir CFDI a este receptor."
                        ),
                    )
                elif sit == "presunto":
                    log_action(request, "stamp_warned_69b",
                               issuer_id=issuer_id, customer_rfc=customer_rfc,
                               situacion=rfc_69b.get("situacion"))

        if issuer.get("facturapi_org_id") in (None, "", 0) or issuer.get("id") == -1:
            raise HTTPException(status_code=400, detail="Configuracion de facturacion no disponible.")
        conn = db()
        try:
            invoice_local_id = invoices_engine.save_invoice_record(
                conn, issuer_id,
                currency=currency, exchange_rate=None,
                payment_form=payment_form, payment_method=payment_method, cfdi_use=cfdi_use,
                customer_rfc=customer_rfc, customer_legal_name=customer_legal_name,
                customer_zip=customer_zip, customer_tax_system=customer_tax_system,
                customer_email=customer_email, export_code="01", tipo_comprobante="I",
            )
            invoices_engine.save_invoice_items(conn, invoice_local_id, items_fact)
            conn.commit()
        except Exception as e:
            conn.close()
            logger.warning("api_invoices_quick insert: %s", e, exc_info=True)
            raise HTTPException(status_code=500, detail="Error al registrar la factura.")
        try:
            invoice = create_invoice(issuer["id"], issuer["facturapi_org_id"], payload_fact)
        except FacturapiError as fe:
            conn.close()
            logger.warning("api invoices quick FacturapiError: issuer_id=%s %s", issuer.get("id"), fe, exc_info=True)
            raise HTTPException(
                status_code=400,
                detail="No se pudo timbrar la factura. Revisa los datos e intenta de nuevo.",
            )
        fact_id = invoice.get("id")
        uuid = invoice.get("uuid")
        total = invoice.get("total")
        invoices_engine.update_invoice_stamp(
            conn, invoice_local_id, issuer_id,
            facturapi_id=fact_id, uuid=uuid, total=total,
        )
        conn.close()
        # Track usage for plan limits
        try:
            from services.billing.plan_guard import record_usage
            record_usage(issuer_id, "invoice")
        except Exception:
            pass  # non-critical

        # Save XML + register in sat_cfdi
        if uuid and fact_id:
            save_xml_and_register_cfdi(
                issuer, issuer_id, uuid, fact_id, currency, cfdi_use,
                payment_method, payment_form, customer_rfc, customer_legal_name,
                items_meta, isr_ret_rate, iva_ret_rate,
            )

        log_action(request, "invoice_created", issuer_id=issuer["id"], invoice_id=fact_id, uuid=(uuid or "")[:36])

        # Replacement flow: auto-cancel the original invoice
        cancel_result = None
        if replaces_uuid and uuid:
            cancel_result = process_replacement_cancel(request, issuer, issuer_id, replaces_uuid, uuid)

        return {"ok": True, "uuid": uuid, "total": total, "cancel_result": cancel_result}


    @router.post("/invoices/bulk_issue")
    def api_invoices_bulk_issue(
        request: Request,
        payload: dict = Body(...),
        issuer: dict = Depends(get_portal_issuer),
    ):
        """Emite N facturas (una por cliente) con 1 producto.

        Fase 1: simplificado (sin retenciones por cliente).
        """
        csrf_service.verify_api_csrf(request)
        _api_rate_check(request, "api_bulk_issue", max_attempts=5, window=60.0)
        user_id = getattr(request.state, "user_id", 0) or 0
        if not subscription_service.can_issuer_use_sync_and_timbrado(issuer.get("id"), user_id):
            raise HTTPException(status_code=402, detail="Actualiza tu plan para emitir facturas.")

        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Payload invalido.")

        customer_ids = payload.get("customer_ids") or payload.get("client_ids") or []
        product_id = payload.get("product_id")
        qty = payload.get("qty", payload.get("quantity", 1))
        unit_price_override = payload.get("unit_price")

        if not isinstance(customer_ids, list) or not customer_ids:
            raise HTTPException(status_code=400, detail="customer_ids es requerido.")
        if not product_id:
            raise HTTPException(status_code=400, detail="product_id es requerido.")
        try:
            product_id = int(product_id)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="product_id invalido.")
        try:
            qty = float(qty)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="qty invalido.")
        if qty <= 0 or qty > 999999:
            raise HTTPException(status_code=400, detail="qty invalido.")
        if unit_price_override is not None and unit_price_override != "":
            try:
                unit_price_override = float(unit_price_override)
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="unit_price invalido.")

        issuer_id = int(issuer.get("id") or 0)
        if issuer_id <= 0:
            raise HTTPException(status_code=401, detail="Sesion invalida.")

        results = []
        conn = db()
        try:
            for cid in customer_ids:
                try:
                    client_id = int(cid)
                except (TypeError, ValueError):
                    results.append({"customer_id": cid, "ok": False, "error": "ID invalido"})
                    continue

                row = conn.execute(
                    "SELECT id, rfc, name, cp, regimen_fiscal, email FROM clients WHERE issuer_id = ? AND id = ? LIMIT 1",
                    (issuer_id, client_id),
                ).fetchone()
                if not row:
                    results.append({"customer_id": client_id, "ok": False, "error": "Cliente no encontrado"})
                    continue
                row = dict(row)
                rfc = (row.get("rfc") or "").strip().upper()
                legal_name = (row.get("name") or "").strip() or rfc
                zip_code = (row.get("cp") or "").strip() or "00000"
                tax_system = (row.get("regimen_fiscal") or "").strip() or "616"
                email = (row.get("email") or "").strip() or None

                if not rfc:
                    results.append({"customer_id": client_id, "ok": False, "error": "RFC vacio"})
                    continue

                cust_row = conn.execute(
                    "SELECT id FROM customer_profiles WHERE issuer_id = ? AND rfc = ? LIMIT 1",
                    (issuer_id, rfc),
                ).fetchone()
                if cust_row:
                    customer_profile_id = int(cust_row["id"])
                else:
                    cust_errors = validate_customer(rfc, legal_name, zip_code, tax_system, email)
                    if cust_errors:
                        results.append({"customer_id": client_id, "ok": False, "error": "; ".join(cust_errors)})
                        continue
                    cur = conn.execute(
                        """
                        INSERT INTO customer_profiles (issuer_id, rfc, legal_name, zip, tax_system, email, alias, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, NULL, datetime('now'), datetime('now'))
                        """,
                        (issuer_id, rfc, legal_name, zip_code, tax_system, email),
                    )
                    customer_profile_id = int(cur.lastrowid)
                    conn.commit()

                try:
                    quick_payload = {
                        "customer_id": customer_profile_id,
                        "product_id": product_id,
                        "quantity": qty,
                    }
                    if unit_price_override is not None and unit_price_override != "":
                        quick_payload["unit_price"] = unit_price_override
                    r = api_invoices_quick(request, payload=quick_payload, issuer=issuer)
                    results.append({"customer_id": client_id, "ok": True, "uuid": r.get("uuid"), "total": r.get("total")})
                except HTTPException as he:
                    results.append({"customer_id": client_id, "ok": False, "error": he.detail})
                except Exception as e:
                    logger.warning("bulk_issue: error emitiendo a client_id=%s: %s", client_id, e, exc_info=True)
                    results.append({"customer_id": client_id, "ok": False, "error": "No se pudo emitir."})
        finally:
            conn.close()

        return ok({"results": results})
