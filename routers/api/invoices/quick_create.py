"""Quick invoice creation and bulk issue routes."""
import hashlib
import logging
import os
from datetime import datetime

from fastapi import Body, Depends, HTTPException, Request

from config import BASE_DIR
from database import db, db_rows, table_exists
from routers.api._helpers import _api_rate_check
from routers.deps import get_portal_issuer
from validators import validate_customer, validate_product

logger = logging.getLogger(__name__)

from facturapi_client import FacturapiError, create_invoice, download_invoice
from facturapi_client import cancel_invoice as facturapi_cancel
from services.action_log import log_action
from services.auth import csrf as csrf_service
from services.billing import subscription as subscription_service
from services.http import ok
from services.invoices import invoices_engine


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

        def _resolve_product(pid: int) -> dict:
            """Resolver producto desde issuer_products o products."""
            rows = db_rows(
                "SELECT id, description, product_key, unit_key, unit_price, iva_rate FROM issuer_products WHERE issuer_id = ? AND id = ? LIMIT 1",
                (issuer_id, pid),
            )
            if rows:
                return rows[0]
            _conn = db()
            try:
                if table_exists(_conn, "products"):
                    row = _conn.execute(
                        "SELECT id, name, clave_prod_serv, clave_unidad, default_unit_price FROM products WHERE issuer_id = ? AND id = ? LIMIT 1",
                        (issuer_id, pid),
                    ).fetchone()
                    if row:
                        row = dict(row)
                        return {
                            "id": row["id"],
                            "description": row.get("name") or "",
                            "product_key": row.get("clave_prod_serv") or "",
                            "unit_key": row.get("clave_unidad") or "E48",
                            "unit_price": float(row.get("default_unit_price") or 0),
                            "iva_rate": 0.16,
                        }
            finally:
                _conn.close()
            raise HTTPException(status_code=404, detail=f"Producto no encontrado: {pid}")

        p = _resolve_product(int(product_id)) if not has_items else None
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

        def _parse_iva_rate(val, default_val: float) -> tuple[float, bool]:
            """Devuelve (iva_rate, iva_exempt). Acepta 'EXENTO'."""
            if val is None or val == "":
                return (max(0.0, min(1.0, float(default_val))), False)
            if isinstance(val, str) and val.strip().upper() == "EXENTO":
                return (0.0, True)
            try:
                n = float(val)
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="IVA rate invalido.")
            n = max(0.0, min(1.0, n))
            return (n, False)

        def _parse_rate(name: str, default: float = 0.0) -> float:
            v = payload.get(name)
            if v is None or v == "":
                return default
            try:
                n = float(v)
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail=f"{name} invalido.")
            return max(0.0, min(1.0, n))

        isr_ret_rate = _parse_rate("isr_ret_rate", 0.0)
        iva_ret_rate = _parse_rate("iva_ret_rate", 0.0)

        cfdi_use = (payload.get("cfdi_use") or payload.get("uso_cfdi") or "G03").strip().upper() or "G03"
        payment_form = (payload.get("payment_form") or "03").strip() or "03"
        payment_method = (payload.get("payment_method") or "PUE").strip().upper() or "PUE"
        currency = (payload.get("currency") or "MXN").strip().upper() or "MXN"

        items_fact = []
        items_meta = []  # para DB invoice_items + sat_cfdi (multi-item)
        if has_items:
            for it in items_in:
                if not isinstance(it, dict):
                    raise HTTPException(status_code=400, detail="items invalidos.")
                pid = it.get("product_id")
                if not pid:
                    raise HTTPException(status_code=400, detail="Cada item requiere product_id.")
                try:
                    pid = int(pid)
                except (TypeError, ValueError):
                    raise HTTPException(status_code=400, detail="product_id invalido en items.")
                qty = float(it.get("quantity", 1))
                if qty <= 0 or qty > 999999:
                    raise HTTPException(status_code=400, detail="Cantidad invalida en items.")
                base_p = _resolve_product(pid)
                description = (it.get("description") or base_p.get("description") or "").strip() or (base_p.get("description") or "").strip()
                product_key = (it.get("product_key") or base_p.get("product_key") or "").strip() or "84111500"
                unit_key = (it.get("unit_key") or base_p.get("unit_key") or "").strip() or "E48"
                up_override = it.get("unit_price")
                if up_override is not None and up_override != "":
                    try:
                        up_override = float(up_override)
                        if up_override < 0:
                            raise HTTPException(status_code=400, detail="Precio unitario no puede ser negativo.")
                    except (TypeError, ValueError):
                        raise HTTPException(status_code=400, detail="Precio unitario invalido.")
                unit_price = float(up_override if up_override is not None and up_override != "" else (base_p.get("unit_price") or 0))
                iva_rate, iva_exempt = _parse_iva_rate(it.get("iva_rate"), float(base_p.get("iva_rate") or 0.16))

                prod_errors = validate_product(description, product_key, unit_key, unit_price)
                if prod_errors:
                    raise HTTPException(status_code=400, detail="; ".join(prod_errors))

                price_to_send = unit_price * (1.0 + iva_rate) if iva_rate else unit_price
                taxes = []
                if not iva_exempt:
                    taxes.append({"type": "IVA", "rate": iva_rate})
                if isr_ret_rate > 0:
                    taxes.append({"type": "ISR", "rate": isr_ret_rate, "withholding": True})
                if iva_ret_rate > 0:
                    taxes.append({"type": "IVA", "rate": iva_ret_rate, "withholding": True})
                items_fact.append(
                    {
                        "quantity": qty,
                        "discount": 0.0,
                        "product": {
                            "description": description,
                            "product_key": product_key,
                            "price": round(price_to_send, 2),
                            "tax_included": True,
                            "taxes": taxes,
                            "unit_key": unit_key,
                        },
                    }
                )
                items_meta.append(
                    {
                        "quantity": qty,
                        "description": description,
                        "product_key": product_key,
                        "unit_key": unit_key,
                        "unit_price": unit_price,  # sin IVA
                        "iva_rate": iva_rate,
                        "price_to_send": round(price_to_send, 2),  # con IVA si aplica
                    }
                )
        else:
            description = (payload.get("description") or p.get("description") or "").strip() or (p.get("description") or "").strip()
            product_key = (payload.get("product_key") or p.get("product_key") or "").strip() or "84111500"
            unit_key = (payload.get("unit_key") or p.get("unit_key") or "").strip() or "E48"
            unit_price = float(unit_price_override if unit_price_override is not None else (p.get("unit_price") or 0))
            iva_rate, iva_exempt = _parse_iva_rate(payload.get("iva_rate"), float(p.get("iva_rate") or 0.16))

            prod_errors = validate_product(description, product_key, unit_key, unit_price)
            if prod_errors:
                raise HTTPException(status_code=400, detail="; ".join(prod_errors))

            price_to_send = unit_price * (1.0 + iva_rate) if iva_rate else unit_price
            taxes = []
            if not iva_exempt:
                taxes.append({"type": "IVA", "rate": iva_rate})
            if isr_ret_rate > 0:
                taxes.append({"type": "ISR", "rate": isr_ret_rate, "withholding": True})
            if iva_ret_rate > 0:
                taxes.append({"type": "IVA", "rate": iva_ret_rate, "withholding": True})
            items_fact.append(
                {
                    "quantity": quantity,
                    "discount": 0.0,
                    "product": {
                        "description": description,
                        "product_key": product_key,
                        "price": round(price_to_send, 2),
                        "tax_included": True,
                        "taxes": taxes,
                        "unit_key": unit_key,
                    },
                }
            )
            items_meta.append(
                {
                    "quantity": quantity,
                    "description": description,
                    "product_key": product_key,
                    "unit_key": unit_key,
                    "unit_price": unit_price,
                    "iva_rate": iva_rate,
                    "price_to_send": round(price_to_send, 2),
                }
            )
        # Replacement flow: if replaces_uuid is set, add related_documents with relationship "04"
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
            invoice = create_invoice(issuer["facturapi_org_id"], payload_fact)
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

        # ----- Guardar XML en storage + registrar en sat_cfdi para descargas /portal/sat/xml|pdf/{uuid} -----
        try:
            if uuid and fact_id:
                xml_bytes = download_invoice(issuer["facturapi_org_id"], fact_id, "xml")
                if isinstance(xml_bytes, str):
                    xml_bytes = xml_bytes.encode("utf-8")
                if xml_bytes:
                    now = datetime.utcnow()
                    year = now.strftime("%Y")
                    month = now.strftime("%m")
                    rel_path = os.path.join("storage", "xml", str(issuer_id), "issued", year, month, f"{uuid}.xml")
                    abs_path = os.path.normpath(os.path.abspath(os.path.join(BASE_DIR, rel_path)))
                    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
                    with open(abs_path, "wb") as f:
                        f.write(xml_bytes)
                    xml_sha256 = hashlib.sha256(xml_bytes).hexdigest()

                    subtotal = sum(float(it["quantity"]) * float(it["unit_price"]) for it in items_meta)
                    iva_amt = sum(float(it["quantity"]) * float(it["unit_price"]) * float(it["iva_rate"]) for it in items_meta)
                    ret_isr_amt = subtotal * float(isr_ret_rate)
                    ret_iva_amt = iva_amt * float(iva_ret_rate)
                    ret_total = ret_isr_amt + ret_iva_amt
                    concepto_txt = (
                        (items_meta[0]["description"] or "")[:220]
                        if len(items_meta) == 1
                        else f"{len(items_meta)} conceptos"
                    )

                    conn2 = db()
                    conn2.execute(
                        """
                        INSERT INTO sat_cfdi (
                          issuer_id, direction, uuid, status, fecha_emision,
                          rfc_emisor, nombre_emisor, rfc_receptor, nombre_receptor,
                          total, moneda, tipo_comprobante, xml_path, uso_cfdi,
                          subtotal, impuestos, retenciones, concepto, metodo_pago, forma_pago,
                          xml_status, xml_sha256, xml_downloaded_at, updated_at
                        ) VALUES (
                          ?, 'issued', ?, 'V', ?,
                          ?, ?, ?, ?,
                          ?, ?, 'I', ?, ?,
                          ?, ?, ?, ?, ?, ?,
                          'ok', ?, datetime('now'), datetime('now')
                        )
                        ON CONFLICT(issuer_id, direction, uuid) DO UPDATE SET
                          xml_path = excluded.xml_path,
                          total = excluded.total,
                          moneda = excluded.moneda,
                          uso_cfdi = excluded.uso_cfdi,
                          subtotal = excluded.subtotal,
                          impuestos = excluded.impuestos,
                          retenciones = excluded.retenciones,
                          concepto = excluded.concepto,
                          metodo_pago = excluded.metodo_pago,
                          forma_pago = excluded.forma_pago,
                          xml_status = excluded.xml_status,
                          xml_sha256 = excluded.xml_sha256,
                          xml_downloaded_at = excluded.xml_downloaded_at,
                          updated_at = datetime('now')
                        """,
                        (
                            issuer_id,
                            uuid,
                            now.isoformat(timespec="seconds"),
                            (issuer.get("rfc") or "").strip().upper() or None,
                            (issuer.get("razon_social") or "").strip() or None,
                            customer_rfc,
                            customer_legal_name,
                            float(total or (subtotal + iva_amt - ret_total)),
                            currency,
                            rel_path,
                            cfdi_use,
                            float(subtotal),
                            float(iva_amt),
                            float(ret_total),
                            concepto_txt,
                            payment_method,
                            payment_form,
                            xml_sha256,
                        ),
                    )
                    conn2.commit()
                    conn2.close()
        except Exception as e:
            logger.warning("api_invoices_quick xml/sat_cfdi: %s", e, exc_info=True)

        log_action(request, "invoice_created", issuer_id=issuer["id"], invoice_id=fact_id, uuid=(uuid or "")[:36])

        # Replacement flow: auto-cancel the original invoice
        cancel_result = None
        if replaces_uuid and uuid:
            try:
                org_id = issuer.get("facturapi_org_id")
                conn_rep = db()
                try:
                    orig = conn_rep.execute(
                        "SELECT id, facturapi_invoice_id FROM invoices WHERE issuer_id = ? AND LOWER(TRIM(uuid)) = LOWER(?) LIMIT 1",
                        (issuer_id, replaces_uuid),
                    ).fetchone()
                    if orig:
                        orig = dict(orig)
                        orig_facturapi_id = orig.get("facturapi_invoice_id")
                        if orig_facturapi_id and org_id:
                            fa_result = facturapi_cancel(org_id, orig_facturapi_id, "01")
                            fa_status = (fa_result.get("status") or "").lower()
                            fa_cs = (fa_result.get("cancellation_status") or "").lower()
                            c_status = "accepted" if fa_status == "canceled" else ("pending" if fa_cs == "pending" else "accepted")
                            c_flag = 1 if c_status == "accepted" else 0
                            now_iso = datetime.utcnow().isoformat(timespec="seconds")
                            conn_rep.execute(
                                """UPDATE invoices
                                   SET cancelled = ?, cancel_status = ?, cancel_motive = '01',
                                       cancelled_at = ?, replacement_uuid = ?
                                   WHERE id = ? AND issuer_id = ?""",
                                (c_flag, c_status, now_iso, uuid, orig["id"], issuer_id),
                            )
                            # Set replaces_uuid on the new invoice
                            conn_rep.execute(
                                "UPDATE invoices SET replaces_uuid = ? WHERE issuer_id = ? AND LOWER(TRIM(uuid)) = LOWER(?)",
                                (replaces_uuid, issuer_id, uuid),
                            )
                            if c_status == "accepted":
                                conn_rep.execute(
                                    "UPDATE sat_cfdi SET status = 'C', updated_at = datetime('now') WHERE issuer_id = ? AND LOWER(TRIM(uuid)) = LOWER(?) AND direction = 'issued'",
                                    (issuer_id, replaces_uuid),
                                )
                            conn_rep.commit()
                            cancel_result = c_status
                            log_action(request, "invoice_cancelled", issuer_id=issuer_id, uuid=replaces_uuid[:36], motive="01", cancel_status=c_status)
                finally:
                    conn_rep.close()
            except Exception as e:
                logger.warning("api_invoices_quick auto-cancel: %s", e, exc_info=True)
                cancel_result = "error"

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

                # Asegurar customer_profile por RFC (reusa validacion existente)
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
