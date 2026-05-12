"""Invoices API routes."""
import hashlib
import logging
import os
import re
import time
from datetime import datetime
from typing import Optional

from fastapi import Body, Depends, File, HTTPException, Query, Request, UploadFile

from config import BASE_DIR
from database import db, db_rows, table_exists
from routers.api._helpers import (
    DEFAULT_LIST_LIMIT,
    MAX_LIST_LIMIT,
    _api_rate_check,
    _load_bootstrap_catalogs,
    _load_fixture,
)
from routers.deps import get_portal_issuer
from validators import validate_customer, validate_product

logger = logging.getLogger(__name__)

try:
    from cfdi_pdf import CLAVE_UNIDAD, FORMA_PAGO, MONEDA, REGIMEN_FISCAL, USO_CFDI
except Exception:
    USO_CFDI = {"G03": "Gastos en general", "G01": "Adquisición de mercancías", "CN01": "Nómina"}
    REGIMEN_FISCAL = {"601": "General de Ley Personas Morales", "612": "Personas Físicas con Actividades Empresariales", "616": "Sin obligaciones fiscales", "626": "Régimen Simplificado de Confianza"}
    FORMA_PAGO = {"03": "Transferencia electrónica", "01": "Efectivo", "99": "Por definir"}
    MONEDA = {"MXN": "Peso Mexicano", "USD": "Dólar Americano"}
    CLAVE_UNIDAD = {"E48": "Unidad de servicio", "EA": "Cada uno", "H87": "Pieza"}

from facturapi_client import FacturapiError, create_invoice, download_invoice
from facturapi_client import cancel_invoice as facturapi_cancel
from services.action_log import log_action
from services.auth import csrf as csrf_service
from services.billing import subscription as subscription_service
from services.http import ok, ok_list
from services.invoices import invoices_engine
from services.ym_helpers import sanitize_ym, ym_sql_filter


def register_invoices_routes(router):
    """Register Invoices routes on the API router."""

    @router.get("/quick-invoice/bootstrap")
    def api_quick_invoice_bootstrap(issuer: dict = Depends(get_portal_issuer)):
        """Devuelve clientes, productos, defaults y catálogos para el widget Factura rápida en Inicio."""
        try:
            conn = db()
            issuer_id = issuer["id"]
            # Clientes (misma fuente que /api/customers y Contactos)
            if table_exists(conn, "clients"):
                conn.execute(
                    """
                    INSERT OR IGNORE INTO customer_profiles (issuer_id, rfc, legal_name, zip, tax_system, email, alias, updated_at)
                    SELECT issuer_id, rfc, COALESCE(name, ''), COALESCE(cp, ''), COALESCE(regimen_fiscal, ''), email, NULL, datetime('now')
                    FROM clients WHERE issuer_id = ?
                    """,
                    (issuer_id,),
                )
                conn.commit()
            rows_c = conn.execute(
                """
                SELECT id, rfc, legal_name, zip, tax_system, email, alias
                FROM customer_profiles WHERE issuer_id = ? ORDER BY COALESCE(alias, ''), rfc
                LIMIT 500
                """,
                (issuer_id,),
            ).fetchall()
            clients = [
                {
                    "id": r["id"],
                    "rfc": r["rfc"],
                    "name": r["legal_name"],
                    "legal_name": r["legal_name"],
                    "zip": r["zip"],
                    "regimen": r["tax_system"],
                    "tax_system": r["tax_system"],
                    "email": r["email"],
                }
                for r in rows_c
            ]
            # Productos (misma fuente que /api/products y Productos)
            if table_exists(conn, "products"):
                rows_p = conn.execute(
                    """
                    SELECT id, name, clave_prod_serv, clave_unidad, unidad, default_unit_price, default_currency
                    FROM products WHERE issuer_id = ? AND COALESCE(active, 1) = 1 ORDER BY name LIMIT 500
                    """,
                    (issuer_id,),
                ).fetchall()
                products = [
                    {
                        "id": r["id"],
                        "name": r["name"] or "",
                        "description": r["name"] or "",
                        "price": float(r["default_unit_price"] or 0),
                        "unit_price": float(r["default_unit_price"] or 0),
                        "currency": (r["default_currency"] or "MXN").strip() or "MXN",
                        "prodserv": r["clave_prod_serv"] or "",
                        "product_key": r["clave_prod_serv"] or "",
                        "unit_key": r["clave_unidad"] or "E48",
                        "unit_name": r["unidad"] or "",
                        "iva_default": 0.16,
                    }
                    for r in rows_p
                ]
            else:
                rows_p = conn.execute(
                    """
                    SELECT id, description, product_key, unit_key, unit_price, iva_rate
                    FROM issuer_products WHERE issuer_id = ? ORDER BY description LIMIT 500
                    """,
                    (issuer_id,),
                ).fetchall()
                products = [
                    {
                        "id": r["id"],
                        "name": r["description"] or "",
                        "description": r["description"] or "",
                        "price": float(r["unit_price"] or 0),
                        "unit_price": float(r["unit_price"] or 0),
                        "currency": "MXN",
                        "prodserv": r["product_key"] or "",
                        "product_key": r["product_key"] or "",
                        "unit_key": r["unit_key"] or "E48",
                        "unit_name": "",
                        "iva_default": float(r["iva_rate"] or 0.16),
                    }
                    for r in rows_p
                ]
            conn.close()
            payload = {
                "clients": clients,
                "products": products,
                "catalogs": _load_bootstrap_catalogs(),
                "defaults": {
                    "currency": "MXN",
                    "exchange_rate": 1.0,
                    "payment_form": "03",
                    "payment_method": "PUE",
                    "uso_cfdi": "G03",
                    "series": None,
                    "folio": None,
                },
                "tax_presets": {
                    "ivas": [
                        {"rate": 0.16, "label": "IVA 16%"},
                        {"rate": 0.0, "label": "IVA 0%"},
                    ],
                    "retenciones": [
                        {"type": "ISR", "rate": 0.10, "label": "Ret ISR 10%"},
                        {"type": "IVA", "rate": 0.1067, "label": "Ret IVA 10.67%"},
                    ],
                },
            }
            return ok(payload)
        except Exception as e:
            logger.warning("quick-invoice bootstrap: %s", e, exc_info=True)
            raise HTTPException(status_code=500, detail="Error al cargar datos para factura rápida.")


    @router.post("/invoices/quick")
    def api_invoices_quick(
        request: Request,
        payload: dict = Body(...),
        issuer: dict = Depends(get_portal_issuer),
    ):
        """Crea y timbra una factura con un solo concepto desde cliente + producto.

        Permite overrides mínimos (receptor, concepto, IVA/retenciones) para el precálculo editable en Home.
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
            raise HTTPException(status_code=400, detail="product_id es requerido (o envía items).")
        try:
            customer_id = int(customer_id)
            if not has_items:
                product_id = int(product_id)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="customer_id/product_id inválidos.")

        # Single-item mode legacy fields
        quantity = None
        unit_price_override = None
        if not has_items:
            quantity = float(payload.get("quantity", 1))
            if quantity <= 0 or quantity > 999999:
                raise HTTPException(status_code=400, detail="Cantidad inválida.")
            unit_price_override = payload.get("unit_price")
            if unit_price_override is not None:
                try:
                    unit_price_override = float(unit_price_override)
                    if unit_price_override < 0:
                        raise HTTPException(status_code=400, detail="Precio unitario no puede ser negativo.")
                except (TypeError, ValueError):
                    raise HTTPException(status_code=400, detail="Precio unitario inválido.")

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
        # ----- Overrides (desde Home precálculo editable) -----
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
                raise HTTPException(status_code=400, detail="IVA rate inválido.")
            n = max(0.0, min(1.0, n))
            return (n, False)

        def _parse_rate(name: str, default: float = 0.0) -> float:
            v = payload.get(name)
            if v is None or v == "":
                return default
            try:
                n = float(v)
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail=f"{name} inválido.")
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
                    raise HTTPException(status_code=400, detail="items inválidos.")
                pid = it.get("product_id")
                if not pid:
                    raise HTTPException(status_code=400, detail="Cada item requiere product_id.")
                try:
                    pid = int(pid)
                except (TypeError, ValueError):
                    raise HTTPException(status_code=400, detail="product_id inválido en items.")
                qty = float(it.get("quantity", 1))
                if qty <= 0 or qty > 999999:
                    raise HTTPException(status_code=400, detail="Cantidad inválida en items.")
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
                        raise HTTPException(status_code=400, detail="Precio unitario inválido.")
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
            raise HTTPException(status_code=400, detail="Configuración de facturación no disponible.")
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


    @router.post("/invoices/{invoice_uuid}/cancel")
    def api_invoices_cancel(
        request: Request,
        invoice_uuid: str,
        payload: dict = Body(...),
        issuer: dict = Depends(get_portal_issuer),
    ):
        """Cancel a stamped invoice via FacturAPI."""
        csrf_service.verify_api_csrf(request)
        _api_rate_check(request, "api_invoice_cancel", max_attempts=5, window=60.0)

        motive = (payload.get("motive") or "").strip()
        if motive not in ("01", "02", "03", "04"):
            raise HTTPException(status_code=400, detail="Motivo de cancelación inválido.")

        issuer_id = issuer["id"]
        uuid_clean = (invoice_uuid or "").strip()
        if not uuid_clean:
            raise HTTPException(status_code=400, detail="UUID requerido.")

        conn = db()
        try:
            row = conn.execute(
                "SELECT id, facturapi_invoice_id, uuid, cancelled FROM invoices WHERE issuer_id = ? AND LOWER(TRIM(uuid)) = LOWER(?) LIMIT 1",
                (issuer_id, uuid_clean),
            ).fetchone()
        finally:
            conn.close()

        if not row:
            raise HTTPException(status_code=404, detail="Factura no encontrada en registros locales.")
        row = dict(row)
        if row.get("cancelled"):
            raise HTTPException(status_code=400, detail="Esta factura ya fue cancelada.")
        facturapi_id = row.get("facturapi_invoice_id")
        if not facturapi_id:
            raise HTTPException(status_code=400, detail="Factura sin ID de FacturAPI — no se puede cancelar.")

        org_id = issuer.get("facturapi_org_id")
        if not org_id:
            raise HTTPException(status_code=400, detail="Configuración de facturación no disponible.")

        try:
            result = facturapi_cancel(org_id, facturapi_id, motive)
        except FacturapiError as fe:
            logger.warning("api_invoices_cancel FacturapiError: issuer_id=%s uuid=%s %s", issuer_id, uuid_clean, fe)
            raise HTTPException(status_code=400, detail=f"Error al cancelar en FacturAPI: {fe}")

        # Determine cancel status from FacturAPI response
        fa_status = (result.get("status") or "").lower()
        fa_cancel_status = (result.get("cancellation_status") or "").lower()

        if fa_status == "canceled":
            cancel_status = "accepted"
            cancelled_flag = 1
        elif fa_cancel_status == "pending":
            cancel_status = "pending"
            cancelled_flag = 0
        else:
            cancel_status = "accepted"
            cancelled_flag = 1

        now_iso = datetime.utcnow().isoformat(timespec="seconds")
        conn = db()
        try:
            conn.execute(
                """UPDATE invoices
                   SET cancelled = ?, cancel_status = ?, cancel_motive = ?, cancelled_at = ?
                   WHERE id = ? AND issuer_id = ?""",
                (cancelled_flag, cancel_status, motive, now_iso, row["id"], issuer_id),
            )
            if cancel_status == "accepted":
                conn.execute(
                    "UPDATE sat_cfdi SET status = 'C', updated_at = datetime('now') WHERE issuer_id = ? AND LOWER(TRIM(uuid)) = LOWER(?) AND direction = 'issued'",
                    (issuer_id, uuid_clean),
                )
            conn.commit()
        finally:
            conn.close()

        log_action(request, "invoice_cancelled", issuer_id=issuer_id, uuid=uuid_clean[:36], motive=motive, cancel_status=cancel_status)
        return ok({"cancel_status": cancel_status, "uuid": uuid_clean})


    @router.get("/invoices/{invoice_uuid}/data")
    def api_invoices_data(
        request: Request,
        invoice_uuid: str,
        issuer: dict = Depends(get_portal_issuer),
    ):
        """Return invoice + items data for pre-filling Quick Invoice (replacement flow)."""
        issuer_id = issuer["id"]
        uuid_clean = (invoice_uuid or "").strip()
        if not uuid_clean:
            raise HTTPException(status_code=400, detail="UUID requerido.")

        conn = db()
        try:
            inv = conn.execute(
                """SELECT id, customer_rfc, customer_legal_name, customer_zip,
                          customer_tax_system, customer_email,
                          payment_form, payment_method, cfdi_use, currency
                   FROM invoices
                   WHERE issuer_id = ? AND LOWER(TRIM(uuid)) = LOWER(?)
                   LIMIT 1""",
                (issuer_id, uuid_clean),
            ).fetchone()
            if not inv:
                raise HTTPException(status_code=404, detail="Factura no encontrada.")
            inv = dict(inv)

            items_rows = conn.execute(
                """SELECT description, product_key, unit_key, unit_price, iva_rate, quantity
                   FROM invoice_items WHERE invoice_id = ? ORDER BY id""",
                (inv["id"],),
            ).fetchall()
            items_rows = [dict(r) for r in items_rows]

            # Try to resolve product_id from issuer_products
            resolved_items = []
            for it in items_rows:
                product_id = None
                match = conn.execute(
                    "SELECT id FROM issuer_products WHERE issuer_id = ? AND description = ? AND product_key = ? LIMIT 1",
                    (issuer_id, it["description"], it["product_key"]),
                ).fetchone()
                if match:
                    product_id = dict(match)["id"]
                resolved_items.append({
                    "product_id": product_id,
                    "description": it["description"],
                    "product_key": it["product_key"],
                    "unit_key": it.get("unit_key"),
                    "unit_price": it["unit_price"],
                    "iva_rate": it.get("iva_rate"),
                    "quantity": it.get("quantity", 1),
                })

            # Try to resolve customer_id from customer_profiles
            customer_id = None
            cust_match = conn.execute(
                "SELECT id FROM customer_profiles WHERE issuer_id = ? AND rfc = ? LIMIT 1",
                (issuer_id, inv["customer_rfc"]),
            ).fetchone()
            if cust_match:
                customer_id = dict(cust_match)["id"]
        finally:
            conn.close()

        return ok({
            "customer_id": customer_id,
            "customer": {
                "rfc": inv["customer_rfc"],
                "legal_name": inv["customer_legal_name"],
                "zip": inv["customer_zip"],
                "tax_system": inv["customer_tax_system"],
                "email": inv.get("customer_email"),
            },
            "items": resolved_items,
            "payment_form": inv.get("payment_form"),
            "payment_method": inv.get("payment_method"),
            "cfdi_use": inv.get("cfdi_use"),
            "currency": inv.get("currency"),
        })


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
            raise HTTPException(status_code=400, detail="Payload inválido.")

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
            raise HTTPException(status_code=400, detail="product_id inválido.")
        try:
            qty = float(qty)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="qty inválido.")
        if qty <= 0 or qty > 999999:
            raise HTTPException(status_code=400, detail="qty inválido.")
        if unit_price_override is not None and unit_price_override != "":
            try:
                unit_price_override = float(unit_price_override)
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="unit_price inválido.")

        issuer_id = int(issuer.get("id") or 0)
        if issuer_id <= 0:
            raise HTTPException(status_code=401, detail="Sesión inválida.")

        results = []
        conn = db()
        try:
            for cid in customer_ids:
                try:
                    client_id = int(cid)
                except (TypeError, ValueError):
                    results.append({"customer_id": cid, "ok": False, "error": "ID inválido"})
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
                    results.append({"customer_id": client_id, "ok": False, "error": "RFC vacío"})
                    continue

                # Asegurar customer_profile por RFC (reusa validación existente)
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


    @router.get("/invoices/issued")
    def api_invoices_issued(
        issuer: dict = Depends(get_portal_issuer),
        ym: str = Query(None, description="Year-month (YYYY-MM)"),
        search: str = Query("", description="Search UUID/RFC/nombre/concepto"),
        status: str = Query("", description="Status filter: vigente, cancelada, all"),
        min_amount: float = Query(None, description="Minimum amount"),
        max_amount: float = Query(None, description="Maximum amount"),
        metodo_pago: str = Query("", description="PUE or PPD"),
        page: int = Query(1, ge=1, description="Page number"),
        per_page: int = Query(DEFAULT_LIST_LIMIT, ge=1, le=MAX_LIST_LIMIT, description="Items per page"),
    ):
        """API endpoint para facturas emitidas con filtros y paginación."""
        fixture = _load_fixture("issued")
        if fixture is not None:
            return fixture
        issuer_id = issuer["id"]
        if not ym:
            ym = datetime.now().strftime("%Y-%m")
        ym = sanitize_ym(ym, datetime.now().strftime("%Y-%m"))
        _ym_filt = ym_sql_filter(ym)

        # Build WHERE clause
        where_parts = [
            "issuer_id = ?",
            "direction = 'issued'",
            "fecha_emision IS NOT NULL",
            _ym_filt,
            "(total IS NULL OR total >= 0.01)",
        ]
        params = [issuer_id, ym]

        # Deduplicate subquery (same as portal route)
        dedup_subquery = f"""
            id IN (
                SELECT id FROM (
                    SELECT id, ROW_NUMBER() OVER (
                        PARTITION BY issuer_id, direction, LOWER(TRIM(uuid))
                        ORDER BY (CASE WHEN COALESCE(total,0) >= 0.01 THEN 0 ELSE 1 END), id
                    ) AS rn
                    FROM sat_cfdi
                    WHERE issuer_id = ? AND direction = 'issued' AND fecha_emision IS NOT NULL
                      AND {_ym_filt} AND (total IS NULL OR total >= 0.01)
                ) WHERE rn = 1
            )
        """
        where_parts.append(dedup_subquery)
        params.extend([issuer_id, ym])

        # Search filter
        if search:
            search_term = f"%{search.upper()}%"
            where_parts.append(
                "(UPPER(COALESCE(uuid,'')) LIKE ? OR UPPER(COALESCE(rfc_receptor,'')) LIKE ? "
                "OR UPPER(COALESCE(nombre_receptor,'')) LIKE ? OR UPPER(COALESCE(concepto,'')) LIKE ?)"
            )
            params.extend([search_term, search_term, search_term, search_term])

        # Status filter
        if status and status.lower() in ("vigente", "cancelada"):
            if status.lower() == "vigente":
                where_parts.append("(status = '1' OR UPPER(TRIM(COALESCE(status,''))) = 'V' OR UPPER(TRIM(COALESCE(status,''))) = 'VIGENTE')")
            elif status.lower() == "cancelada":
                where_parts.append("(status = '0' OR UPPER(TRIM(COALESCE(status,''))) = 'C' OR UPPER(TRIM(COALESCE(status,''))) LIKE 'CANCEL%')")

        # Amount filters
        if min_amount is not None:
            where_parts.append("COALESCE(total, 0) >= ?")
            params.append(min_amount)
        if max_amount is not None:
            where_parts.append("COALESCE(total, 0) <= ?")
            params.append(max_amount)

        # Metodo pago filter
        if metodo_pago and metodo_pago.upper() in ("PUE", "PPD"):
            where_parts.append("UPPER(TRIM(COALESCE(metodo_pago,''))) = ?")
            params.append(metodo_pago.upper())

        where_clause = " AND ".join(where_parts)

        # Count total (row_factory devuelve dict; la clave es el nombre de columna, no el índice)
        try:
            conn = db()
            count_row = conn.execute(
                f"SELECT COUNT(*) AS c FROM sat_cfdi WHERE {where_clause}",
                tuple(params)
            ).fetchone()
            total_count = int(count_row.get("c", 0)) if count_row else 0
            conn.close()
        except Exception as e:
            logger.exception("Error counting invoices")
            raise HTTPException(status_code=500, detail="Error al contar facturas")

        # Fetch paginated results (solo columnas usadas en el listado para payload pequeño)
        try:
            offset = (page - 1) * per_page
            rows = db_rows(
                f"""
                SELECT uuid, fecha_emision, rfc_receptor, nombre_receptor, concepto, total, moneda,
                       COALESCE(impuestos, 0) AS impuestos, COALESCE(retenciones, 0) AS retenciones,
                       metodo_pago, status, xml_path
                FROM sat_cfdi
                WHERE {where_clause}
                ORDER BY fecha_emision DESC
                LIMIT ? OFFSET ?
                """,
                tuple(params) + (per_page, offset)
            )
        except Exception as e:
            logger.exception("Error fetching invoices")
            raise HTTPException(status_code=500, detail="Error al obtener facturas")

        return {
            "data": rows,
            "pagination": {
                "page": page,
                "per_page": per_page,
                "total": total_count,
                "pages": (total_count + per_page - 1) // per_page if total_count > 0 else 0,
            },
            "filters": {
                "ym": ym,
                "search": search,
                "status": status,
                "min_amount": min_amount,
                "max_amount": max_amount,
                "metodo_pago": metodo_pago,
            }
        }


    @router.get("/invoices/received")
    def api_invoices_received(
        issuer: dict = Depends(get_portal_issuer),
        ym: str = Query(None, description="Year-month (YYYY-MM)"),
        search: str = Query("", description="Search UUID/RFC/nombre/concepto"),
        status: str = Query("", description="Status filter: vigente, cancelada, all"),
        min_amount: float = Query(None, description="Minimum amount"),
        max_amount: float = Query(None, description="Maximum amount"),
        metodo_pago: str = Query("", description="PUE or PPD"),
        match_filter: str = Query("", description="Conciliación: none|probable"),
        page: int = Query(1, ge=1, description="Page number"),
        per_page: int = Query(DEFAULT_LIST_LIMIT, ge=1, le=MAX_LIST_LIMIT, description="Items per page"),
    ):
        """API endpoint para facturas recibidas con filtros y paginación."""
        fixture = _load_fixture("received")
        if fixture is not None:
            return fixture
        issuer_id = issuer["id"]
        if not ym:
            ym = datetime.now().strftime("%Y-%m")
        ym = sanitize_ym(ym, datetime.now().strftime("%Y-%m"))
        _ym_filt = ym_sql_filter(ym)

        # Build WHERE clause
        where_parts = [
            "issuer_id = ?",
            "direction = 'received'",
            "fecha_emision IS NOT NULL",
            _ym_filt,
            "total IS NOT NULL AND total >= 0.01",
            "(tipo_comprobante IS NULL OR UPPER(TRIM(tipo_comprobante)) != 'N')",
        ]
        params = [issuer_id, ym]

        # Deduplicate subquery
        dedup_subquery = f"""
            id IN (
                SELECT id FROM (
                    SELECT id, ROW_NUMBER() OVER (
                        PARTITION BY issuer_id, direction, LOWER(TRIM(uuid))
                        ORDER BY id
                    ) AS rn
                    FROM sat_cfdi
                    WHERE issuer_id = ? AND direction = 'received' AND fecha_emision IS NOT NULL
                      AND {_ym_filt} AND total IS NOT NULL AND total >= 0.01
                      AND (tipo_comprobante IS NULL OR UPPER(TRIM(tipo_comprobante)) != 'N')
                ) WHERE rn = 1
            )
        """
        where_parts.append(dedup_subquery)
        params.extend([issuer_id, ym])

        # Search filter
        if search:
            search_term = f"%{search.upper()}%"
            where_parts.append(
                "(UPPER(COALESCE(uuid,'')) LIKE ? OR UPPER(COALESCE(rfc_emisor,'')) LIKE ? "
                "OR UPPER(COALESCE(nombre_emisor,'')) LIKE ? OR UPPER(COALESCE(concepto,'')) LIKE ?)"
            )
            params.extend([search_term, search_term, search_term, search_term])

        # Status filter
        if status and status.lower() in ("vigente", "cancelada"):
            if status.lower() == "vigente":
                where_parts.append("(status = '1' OR UPPER(TRIM(COALESCE(status,''))) = 'V' OR UPPER(TRIM(COALESCE(status,''))) = 'VIGENTE')")
            elif status.lower() == "cancelada":
                where_parts.append("(status = '0' OR UPPER(TRIM(COALESCE(status,''))) = 'C' OR UPPER(TRIM(COALESCE(status,''))) LIKE 'CANCEL%')")

        # Amount filters
        if min_amount is not None:
            where_parts.append("COALESCE(total, 0) >= ?")
            params.append(min_amount)
        if max_amount is not None:
            where_parts.append("COALESCE(total, 0) <= ?")
            params.append(max_amount)

        # Metodo pago filter
        if metodo_pago and metodo_pago.upper() in ("PUE", "PPD"):
            where_parts.append("UPPER(TRIM(COALESCE(metodo_pago,''))) = ?")
            params.append(metodo_pago.upper())

        # Conciliación (mismo modelo que bank/movements)
        mf = (match_filter or "").strip().lower()
        if mf in ("none", "probable"):
            # Solo si existe tabla; si no existe, no filtrar (degrada a 'todos')
            try:
                conn0 = db()
                has_matches = ("bank_invoice_matches" in {r[0] for r in conn0.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()})
                conn0.close()
            except Exception:
                has_matches = False
            if has_matches:
                if mf == "probable":
                    where_parts.append(
                        """EXISTS (
                             SELECT 1 FROM bank_invoice_matches bim
                             WHERE bim.issuer_id = sat_cfdi.issuer_id
                               AND bim.cfdi_id = sat_cfdi.id
                               AND bim.status IN ('suggested','confirmed')
                               AND COALESCE(bim.score,0) >= 80
                           )"""
                    )
                elif mf == "none":
                    where_parts.append(
                        """NOT EXISTS (
                             SELECT 1 FROM bank_invoice_matches bim
                             WHERE bim.issuer_id = sat_cfdi.issuer_id
                               AND bim.cfdi_id = sat_cfdi.id
                               AND bim.status IN ('suggested','confirmed')
                               AND COALESCE(bim.score,0) >= 50
                           )"""
                    )

        where_clause = " AND ".join(where_parts)

        # Count total (row_factory devuelve dict)
        try:
            conn = db()
            count_row = conn.execute(
                f"SELECT COUNT(*) AS c FROM sat_cfdi WHERE {where_clause}",
                tuple(params)
            ).fetchone()
            total_count = int(count_row.get("c", 0)) if count_row else 0
            conn.close()
        except Exception as e:
            logger.exception("Error counting invoices")
            raise HTTPException(status_code=500, detail="Error al contar facturas")

        # Fetch paginated results
        try:
            offset = (page - 1) * per_page
            rows = db_rows(
                f"""
                SELECT uuid, fecha_emision, rfc_emisor, nombre_emisor, concepto, total, moneda,
                       COALESCE(impuestos, 0) AS impuestos, COALESCE(retenciones, 0) AS retenciones,
                       metodo_pago, status, xml_path,
                       (
                         SELECT bm.id
                         FROM bank_invoice_matches bim
                         JOIN bank_movements bm ON bm.id = bim.bank_movement_id AND bm.issuer_id = bim.issuer_id
                         WHERE bim.issuer_id = sat_cfdi.issuer_id
                           AND bim.cfdi_id = sat_cfdi.id
                           AND bim.status IN ('suggested','confirmed')
                         ORDER BY bim.score DESC, bim.id DESC
                         LIMIT 1
                       ) AS probable_movement_id,
                       (
                         SELECT bm.fecha
                         FROM bank_invoice_matches bim
                         JOIN bank_movements bm ON bm.id = bim.bank_movement_id AND bm.issuer_id = bim.issuer_id
                         WHERE bim.issuer_id = sat_cfdi.issuer_id
                           AND bim.cfdi_id = sat_cfdi.id
                           AND bim.status IN ('suggested','confirmed')
                         ORDER BY bim.score DESC, bim.id DESC
                         LIMIT 1
                       ) AS probable_movement_fecha,
                       (
                         SELECT COALESCE(bm.deposito, 0) - COALESCE(bm.retiro, 0)
                         FROM bank_invoice_matches bim
                         JOIN bank_movements bm ON bm.id = bim.bank_movement_id AND bm.issuer_id = bim.issuer_id
                         WHERE bim.issuer_id = sat_cfdi.issuer_id
                           AND bim.cfdi_id = sat_cfdi.id
                           AND bim.status IN ('suggested','confirmed')
                         ORDER BY bim.score DESC, bim.id DESC
                         LIMIT 1
                       ) AS probable_movement_amount,
                       (
                         SELECT bm.descripcion
                         FROM bank_invoice_matches bim
                         JOIN bank_movements bm ON bm.id = bim.bank_movement_id AND bm.issuer_id = bim.issuer_id
                         WHERE bim.issuer_id = sat_cfdi.issuer_id
                           AND bim.cfdi_id = sat_cfdi.id
                           AND bim.status IN ('suggested','confirmed')
                         ORDER BY bim.score DESC, bim.id DESC
                         LIMIT 1
                       ) AS probable_movement_desc,
                       (
                         SELECT bim.score
                         FROM bank_invoice_matches bim
                         WHERE bim.issuer_id = sat_cfdi.issuer_id
                           AND bim.cfdi_id = sat_cfdi.id
                           AND bim.status IN ('suggested','confirmed')
                         ORDER BY bim.score DESC, bim.id DESC
                         LIMIT 1
                       ) AS probable_movement_score,
                       (
                         SELECT bim.status
                         FROM bank_invoice_matches bim
                         WHERE bim.issuer_id = sat_cfdi.issuer_id
                           AND bim.cfdi_id = sat_cfdi.id
                           AND bim.status IN ('suggested','confirmed')
                         ORDER BY bim.score DESC, bim.id DESC
                         LIMIT 1
                       ) AS probable_movement_status
                FROM sat_cfdi
                WHERE {where_clause}
                ORDER BY fecha_emision DESC
                LIMIT ? OFFSET ?
                """,
                tuple(params) + (per_page, offset)
            )
        except Exception as e:
            logger.exception("Error fetching invoices")
            raise HTTPException(status_code=500, detail="Error al obtener facturas")

        return {
            "data": rows,
            "pagination": {
                "page": page,
                "per_page": per_page,
                "total": total_count,
                "pages": (total_count + per_page - 1) // per_page if total_count > 0 else 0,
            },
            "filters": {
                "ym": ym,
                "search": search,
                "status": status,
                "min_amount": min_amount,
                "max_amount": max_amount,
                "metodo_pago": metodo_pago,
                "match_filter": match_filter,
            }
        }



    @router.post("/movements/invoice")
    def api_foreign_invoice_create(
        request: Request,
        issuer: dict = Depends(get_portal_issuer),
        body: dict = Body(...),
    ):
        """Create a foreign invoice record."""
        csrf_service.verify_api_csrf(request)
        issuer_id = int(issuer.get("id") or 0)
        if issuer_id <= 0:
            raise HTTPException(status_code=401, detail="Sesión inválida")
        from services.invoices import foreign_invoices as fi
        fi.ensure_table()
        tipo = (body.get("tipo") or "").strip().upper()
        fecha = (body.get("fecha") or "").strip()
        invoice_number = (body.get("invoice_number") or "").strip()
        empresa = (body.get("empresa") or "").strip()
        descripcion = (body.get("descripcion") or "").strip()
        moneda = (body.get("moneda") or "USD").strip()
        monto_original = body.get("monto_original")
        tipo_cambio = body.get("tipo_cambio")
        if not all([tipo, fecha, invoice_number, empresa, descripcion, monto_original, tipo_cambio]):
            raise HTTPException(status_code=422, detail="Campos requeridos: tipo, fecha, invoice_number, empresa, descripcion, monto_original, tipo_cambio")
        try:
            monto_original = float(monto_original)
            tipo_cambio = float(tipo_cambio)
        except (TypeError, ValueError):
            raise HTTPException(status_code=422, detail="monto_original y tipo_cambio deben ser numéricos")
        if monto_original <= 0 or tipo_cambio <= 0:
            raise HTTPException(status_code=422, detail="monto y tipo de cambio deben ser mayores a 0")
        pais = (body.get("pais") or "").strip() or None
        tax_id = (body.get("tax_id") or "").strip() or None
        forma_pago = (body.get("forma_pago") or "").strip() or None
        referencia_pago = (body.get("referencia_pago") or "").strip() or None
        notas = (body.get("notas") or "").strip() or None
        row = fi.create(
            issuer_id, tipo, fecha, invoice_number, empresa, descripcion,
            moneda, monto_original, tipo_cambio, forma_pago=forma_pago,
            pais=pais, tax_id=tax_id, referencia_pago=referencia_pago, notas=notas,
        )
        return ok(row)


    @router.get("/invoices/foreign")
    def api_foreign_invoices_list(
        request: Request,
        issuer: dict = Depends(get_portal_issuer),
        ym: Optional[str] = Query(None),
        tipo: Optional[str] = Query(None),
        limit: int = Query(200, ge=1, le=500),
        offset: int = Query(0, ge=0),
    ):
        """List foreign invoices for the current issuer."""
        issuer_id = int(issuer.get("id") or 0)
        if issuer_id <= 0:
            raise HTTPException(status_code=401, detail="Sesión inválida")
        from services.invoices import foreign_invoices as fi
        fi.ensure_table()
        items = fi.list_invoices(issuer_id, period_month=ym, tipo=tipo, limit=limit, offset=offset)
        total = fi.count_invoices(issuer_id, period_month=ym)
        return ok_list(items, total)


    @router.delete("/invoices/foreign/{invoice_id}")
    def api_foreign_invoice_delete(invoice_id: int, request: Request, issuer: dict = Depends(get_portal_issuer)):
        """Delete a foreign invoice."""
        csrf_service.verify_api_csrf(request)
        issuer_id = int(issuer.get("id") or 0)
        if issuer_id <= 0:
            raise HTTPException(status_code=401, detail="Sesión inválida")
        from services.invoices import foreign_invoices as fi
        fi.ensure_table()
        conn = db()
        try:
            cur = conn.execute("DELETE FROM foreign_invoices WHERE id = ? AND issuer_id = ?", (invoice_id, issuer_id))
            conn.commit()
            deleted = cur.rowcount > 0
        finally:
            conn.close()
        if not deleted:
            raise HTTPException(status_code=404, detail="Invoice no encontrado")
        return ok({"deleted": True})


    @router.get("/invoices/foreign/{invoice_id}/pdf")
    def api_foreign_invoice_pdf(invoice_id: int, request: Request, issuer: dict = Depends(get_portal_issuer)):
        """Serve the stored PDF for a foreign invoice (opens in browser)."""
        from fastapi.responses import FileResponse
        issuer_id = int(issuer.get("id") or 0)
        if issuer_id <= 0:
            raise HTTPException(status_code=401, detail="Sesión inválida")
        rows = db_rows("SELECT archivo FROM foreign_invoices WHERE id = ? AND issuer_id = ?", (invoice_id, issuer_id))
        if not rows or not rows[0].get("archivo"):
            raise HTTPException(status_code=404, detail="PDF no disponible")
        archivo_rel = rows[0]["archivo"]
        storage_root = os.environ.get("APP_STORAGE_PATH", "").strip() or os.path.join(os.path.dirname(os.path.dirname(__file__)), "storage")
        abs_path = os.path.normpath(os.path.join(storage_root, archivo_rel))
        # Security: ensure path is under storage_root
        if not abs_path.startswith(os.path.normpath(storage_root)):
            raise HTTPException(status_code=403, detail="Acceso denegado")
        if not os.path.isfile(abs_path):
            raise HTTPException(status_code=404, detail="Archivo no encontrado")
        from services import file_access_log
        file_access_log.log_file_access(
            request=request, action="view_foreign_invoice_pdf",
            issuer_id=issuer_id, user_id=getattr(getattr(request, "state", None), "user_id", None),
            file_path=archivo_rel,
            entity="foreign_invoice", entity_id=str(invoice_id),
        )
        return FileResponse(abs_path, media_type="application/pdf", headers={"Content-Disposition": "inline"})


    # ── Exchange rates ──────────────────────────────────────────────

    @router.post("/invoices/extract-pdf")
    def api_invoice_extract_pdf(
        request: Request,
        issuer: dict = Depends(get_portal_issuer),
        file: UploadFile = File(...),
        auto_save: bool = Query(False, alias="auto_save"),
    ):
        """Extract invoice data from a PDF.  When auto_save=true, also persist.
        Sync endpoint so FastAPI runs it in a threadpool (pdfplumber + SQLite are blocking).
        """
        csrf_service.verify_api_csrf(request)
        _api_rate_check(request, "invoice_extract_pdf", max_attempts=12, window=60.0)
        if not file.filename or not file.filename.lower().endswith(".pdf"):
            raise HTTPException(status_code=400, detail="Solo se aceptan archivos PDF")
        max_pdf_size = 15 * 1024 * 1024
        import tempfile
        tmp_path = None
        try:
            size = 0
            chunks: list[bytes] = []
            while True:
                chunk = file.file.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > max_pdf_size:
                    raise HTTPException(status_code=400, detail="PDF demasiado grande (máx 15 MB)")
                chunks.append(chunk)
            if size <= 0:
                raise HTTPException(status_code=400, detail="Archivo vacío")
            content = b"".join(chunks)
            if not content.startswith(b"%PDF"):
                raise HTTPException(status_code=400, detail="El archivo no parece ser un PDF válido")
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                tmp.write(content)
                tmp_path = tmp.name
            import pdfplumber
            text = ""
            tables: list[list] = []
            with pdfplumber.open(tmp_path) as pdf:
                for page in pdf.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text += page_text + "\n"
                    try:
                        for t in (page.extract_tables() or []):
                            if t:
                                tables.append(t)
                    except Exception:
                        pass
            if not text.strip():
                raise HTTPException(status_code=400, detail="No se pudo extraer texto del PDF. Puede ser un PDF escaneado (imagen).")
            data = _parse_invoice_text(text, tables)

            if auto_save:
                issuer_id = int(issuer.get("id") or 0)
                if issuer_id <= 0:
                    raise HTTPException(status_code=401, detail="Sesión inválida")
                from services.invoices import foreign_invoices as fi
                fi.ensure_table()
                # Fill defaults for auto-save
                from services.invoices.exchange_rates import get_rate
                moneda = data.get("moneda") or "USD"
                tipo = data.get("tipo") or "GASTO"
                fecha = data.get("fecha") or datetime.now().strftime("%Y-%m-%d")
                period = fecha[:7] if len(fecha) >= 7 else datetime.now().strftime("%Y-%m")
                tipo_cambio = get_rate(moneda, period)
                inv_num = data.get("invoice_number") or (file.filename or "").replace(".pdf", "").replace(".PDF", "") or "PDF-IMPORT"
                empresa = data.get("empresa") or "Empresa extranjera"
                descripcion = data.get("descripcion") or (", ".join(data.get("productos") or [])[:200]) or "Invoice importado desde PDF"
                monto = data.get("monto_original") or 0
                if monto <= 0:
                    return ok({**data, "auto_saved": False, "reason": "no_amount"})
                # Deduplication check
                if fi.is_duplicate(issuer_id, inv_num, empresa):
                    return ok({**data, "auto_saved": False, "duplicate": True, "reason": "duplicate"})
                # Save PDF to storage
                archivo_rel = None
                try:
                    storage_root = os.environ.get("APP_STORAGE_PATH", "").strip() or os.path.join(os.path.dirname(os.path.dirname(__file__)), "storage")
                    fi_dir = os.path.join(storage_root, "foreign_invoices", str(issuer_id))
                    os.makedirs(fi_dir, exist_ok=True)
                    safe_name = re.sub(r"[^\w\-.]", "_", file.filename or "invoice.pdf")[:80]
                    dest = os.path.join(fi_dir, f"{inv_num}_{safe_name}")
                    if os.path.exists(dest):
                        # Add timestamp to avoid overwrite
                        base, ext = os.path.splitext(dest)
                        dest = f"{base}_{int(time.time())}{ext}"
                    import shutil
                    shutil.copy2(tmp_path, dest)
                    archivo_rel = os.path.relpath(dest, storage_root)
                except Exception:
                    logger.warning("Could not save foreign invoice PDF to storage", exc_info=True)
                row = fi.create(
                    issuer_id, tipo, fecha, inv_num, empresa, descripcion,
                    moneda, monto, tipo_cambio,
                    forma_pago=data.get("forma_pago"),
                    pais=data.get("pais"),
                    tax_id=data.get("tax_id"),
                    archivo=archivo_rel,
                )
                return ok({**data, "auto_saved": True, "record": row, "tipo_cambio_used": tipo_cambio})

            return ok(data)
        except HTTPException:
            raise
        except Exception as e:
            logger.exception("Error extracting invoice PDF")
            raise HTTPException(status_code=500, detail=f"Error al procesar PDF: {str(e)}")
        finally:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass


    # ── Invoice PDF parser ──────────────────────────────────────────

    _MONTH_MAP = {
        "january": "01", "february": "02", "march": "03", "april": "04",
        "may": "05", "june": "06", "july": "07", "august": "08",
        "september": "09", "october": "10", "november": "11", "december": "12",
        "jan": "01", "feb": "02", "mar": "03", "apr": "04",
        "jun": "06", "jul": "07", "aug": "08", "sep": "09",
        "oct": "10", "nov": "11", "dec": "12",
        "enero": "01", "febrero": "02", "marzo": "03", "abril": "04",
        "mayo": "05", "junio": "06", "julio": "07", "agosto": "08",
        "septiembre": "09", "octubre": "10", "noviembre": "11", "diciembre": "12",
    }

    _COUNTRY_MAP = {
        "United States": "US", "USA": "US", "U.S.A.": "US", "U.S.": "US",
        "Canada": "CA", "United Kingdom": "GB", "UK": "GB", "Great Britain": "GB",
        "Germany": "DE", "Deutschland": "DE", "France": "FR",
        "Spain": "ES", "España": "ES",
        "Colombia": "CO", "Argentina": "AR", "Chile": "CL",
        "Brazil": "BR", "Brasil": "BR",
        "Mexico": "MX", "México": "MX",
        "Italy": "IT", "Italia": "IT",
        "Netherlands": "NL", "Portugal": "PT",
        "Australia": "AU", "New Zealand": "NZ",
        "Japan": "JP", "China": "CN", "India": "IN",
        "Ireland": "IE", "Switzerland": "CH",
        "Israel": "IL", "Singapore": "SG",
        "Denmark": "DK", "Danmark": "DK", "DENMARK": "DK",
        "Sweden": "SE", "Norway": "NO", "Finland": "FI",
        "Belgium": "BE", "Austria": "AT",
    }

    _COMPANY_SUFFIXES = re.compile(
        r"\b(?:Inc\.?|LLC|Ltd\.?|Corp\.?|GmbH|SA\b|S\.?A\.?\s*de\s*C\.?V\.?|"
        r"S\.?L\.?|S\.?R\.?L\.?|Co\.?|PLC|AG|BV|NV|Pty|Limited|Corporation|Company|Incorporated)\b",
        re.IGNORECASE,
    )

    _SKIP_HEADER_RE = re.compile(
        r"^(?:Invoice|Date|Bill\s*To|Ship\s*To|To:|Sold\s*To|Remit|Due|Terms|Page|P\.?O\.?\s|"
        r"Phone|Fax|Email|Tel|www\.|http|Tax\s*ID|EIN|VAT|TIN|Subtotal|Total|\d{1,2}[/\-\.]\d|"
        r"\d{4}-\d{2}|Amount|Payment|Balance|Description|Item|Qty|Quantity|Rate|Price|Unit|"
        r"Issued|Paid|Order|Status|Account|Billing|Receipt|Ref|Reference|"
        r"Statement|Period|Subscription|Thank|Dear|Hello|Hi\b|Note|Memo)",
        re.IGNORECASE,
    )


    def _parse_date(raw: str) -> str | None:
        """Try to normalize a date string to YYYY-MM-DD."""
        raw = raw.strip()
        # Strip ordinal suffixes: 24th → 24, 1st → 1, 2nd → 2, 3rd → 3
        cleaned = re.sub(r"(\d{1,2})(?:st|nd|rd|th)\b", r"\1", raw)
        # ISO
        if re.match(r"\d{4}-\d{2}-\d{2}$", cleaned):
            return cleaned
        # Named month: "15 March 2024" / "15 March, 2024"
        m = re.match(r"(\d{1,2})\s+(\w+),?\s+(\d{4})$", cleaned)
        if m:
            day, mon, year = m.group(1), m.group(2).lower(), m.group(3)
            if mon in _MONTH_MAP:
                return f"{year}-{_MONTH_MAP[mon]}-{day.zfill(2)}"
        # Named month: "March 15, 2024" / "March 15 2024"
        m = re.match(r"(\w+)\s+(\d{1,2}),?\s+(\d{4})$", cleaned)
        if m:
            mon, day, year = m.group(1).lower(), m.group(2), m.group(3)
            if mon in _MONTH_MAP:
                return f"{year}-{_MONTH_MAP[mon]}-{day.zfill(2)}"
        # DD/MM/YYYY or MM/DD/YYYY (also handles 2-digit year)
        parts = re.split(r"[/\-\.]", cleaned)
        if len(parts) == 3:
            if len(parts[2]) == 2:
                parts[2] = "20" + parts[2]
            try:
                a, b, c = int(parts[0]), int(parts[1]), int(parts[2])
            except ValueError:
                return cleaned
            if c > 1900:
                if a > 12:  # DD/MM/YYYY
                    return f"{c}-{str(b).zfill(2)}-{str(a).zfill(2)}"
                else:  # MM/DD/YYYY (US default)
                    return f"{c}-{str(a).zfill(2)}-{str(b).zfill(2)}"
            elif a > 1900:  # YYYY/MM/DD
                return f"{a}-{str(b).zfill(2)}-{str(c).zfill(2)}"
        return cleaned


    def _parse_amount(raw: str) -> float | None:
        """Parse an amount string handling US and EU formats."""
        raw = raw.strip()
        # Remove currency symbols
        raw = re.sub(r"[€$£¥]", "", raw).strip()
        raw = re.sub(r"^(USD|EUR|GBP|CAD|MXN)\s*", "", raw, flags=re.IGNORECASE).strip()
        raw = re.sub(r"\s*(USD|EUR|GBP|CAD|MXN)$", "", raw, flags=re.IGNORECASE).strip()
        if not raw:
            return None
        # European: 1.234,56 → 1234.56
        if re.match(r"[\d\.]+,\d{2}$", raw):
            raw = raw.replace(".", "").replace(",", ".")
        else:
            raw = raw.replace(",", "")
        try:
            v = float(raw)
            return v if v > 0 else None
        except ValueError:
            return None


    def _extract_amounts_from_tables(tables: list) -> list[dict]:
        """Extract item descriptions and amounts from pdfplumber tables."""
        items: list[dict] = []
        for table in tables:
            if not table or len(table) < 2:
                continue
            header = table[0]
            if not header:
                continue
            # Find description and amount columns by header text
            desc_col = amt_col = qty_col = rate_col = None
            header_lower = [(str(h or "").lower().strip()) for h in header]
            for i, h in enumerate(header_lower):
                if any(k in h for k in (
                    "description", "item", "service", "concept", "producto", "descripci",
                    "detalle", "partida", "product", "line item", "memo", "nombre",
                )):
                    desc_col = i
                if any(k in h for k in ("amount", "total", "monto", "importe", "betrag", "sum")):
                    amt_col = i
                if any(k in h for k in ("qty", "quantity", "cantidad", "menge", "units", "hours", "hrs")):
                    qty_col = i
                if any(k in h for k in ("rate", "price", "precio", "unit", "preis", "cost", "tarifa")):
                    rate_col = i
            if desc_col is None:
                # Try first text column
                for i, h in enumerate(header_lower):
                    if h and not any(c.isdigit() for c in h):
                        desc_col = i
                        break
            if amt_col is None and rate_col is not None:
                amt_col = rate_col
            for row in table[1:]:
                if not row:
                    continue
                desc = str(row[desc_col] or "").strip() if desc_col is not None and desc_col < len(row) else ""
                amt_str = str(row[amt_col] or "").strip() if amt_col is not None and amt_col < len(row) else ""
                # Skip subtotal/total/tax rows in table items
                if desc and re.match(r"^(subtotal|total|tax|iva|vat|impuesto|descuento|discount|shipping|envío)", desc, re.IGNORECASE):
                    continue
                if desc and len(desc) > 2:
                    amt = _parse_amount(amt_str) if amt_str else None
                    items.append({"descripcion": desc, "monto": amt})
        return items


    def _parse_invoice_text(text: str, tables: list | None = None) -> dict:
        """Parse invoice text and extract structured fields."""
        result: dict = {
            "invoice_number": None,
            "fecha": None,
            "empresa": None,
            "pais": None,
            "moneda": None,
            "monto_original": None,
            "descripcion": None,
            "tax_id": None,
            "productos": [],
            "forma_pago": None,
            "tipo": None,
        }
        lines = [l.strip() for l in text.strip().split("\n") if l.strip()]

        # ── Invoice number ──────────────────────────────────────────
        # Known keywords that are NOT invoice numbers
        _NOT_INVOICE_NUM = {"order", "seller", "receipt", "invoice", "date", "from", "to", "item", "price", "total", "paid", "id",
                             "number", "details", "summary", "description", "amount", "created", "status", "type"}
        for pat in [
            r"(?:Invoice|Inv|Factura|Receipt|Bill|Rechnung|Nota)\s*(?:#|No\.?|Number|Num|Número|Nr\.?)\s*[:\s]*([A-Za-z0-9][\w\-\/\.]+)",
            r"(?:Invoice\s+ID|Order\s+ID|Order\s*#|Ref|Reference|Referencia)\s*[:\s#]*([A-Za-z0-9][\w\-\/\.]+)",
            r"(?:Invoice|INV|FACTURA|RECEIPT)[ \t]*[:#\-]+[:#\- \t]*([A-Za-z0-9][\w\-\/\.]+)",
            r"(?:Invoice|Factura)\s+([A-Za-z0-9][\w\-]{3,30})",
            r"#\s*([A-Z0-9][\w\-]{2,20})",
        ]:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                val = m.group(1).strip().rstrip(".")
                if len(val) >= 2 and val.lower() not in _NOT_INVOICE_NUM:
                    result["invoice_number"] = val
                    break

        # ── Date ────────────────────────────────────────────────────
        _DATE_LABEL = (
            r"(?:Date|Fecha|Invoice\s*Date|Issue\s*Date|Datum|"
            r"Issued\s*(?:at|on)?|Billed\s*(?:On|Date)?|"
            r"Order\s*Created|Paid\s*(?:on|In\s*Full)?|Due\s*(?:On|Date)?)"
        )
        date_patterns = [
            # Labeled dates
            _DATE_LABEL + r"\s*[:\s]+(\d{4}-\d{2}-\d{2})",
            _DATE_LABEL + r"\s*[:\s]+(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4})",
            _DATE_LABEL + r"\s*[:\s]+(\w+\s+\d{1,2}(?:st|nd|rd|th)?,?\s*\d{4})",
            _DATE_LABEL + r"\s*[:\s]+(\d{1,2}(?:st|nd|rd|th)?\s+\w+,?\s*\d{4})",
            # Unlabeled ISO
            r"(\d{4}-\d{2}-\d{2})",
            # Unlabeled named month (with optional ordinal suffix)
            r"(\w+\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4})",
            r"(\d{1,2}(?:st|nd|rd|th)?\s+\w+\s+\d{4})",
            # Unlabeled numeric
            r"(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{4})",
        ]
        for pat in date_patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                parsed = _parse_date(m.group(1))
                if parsed and re.match(r"\d{4}-\d{2}-\d{2}$", parsed):
                    result["fecha"] = parsed
                    break
                elif parsed:
                    result["fecha"] = parsed
                    break

        # ── Currency (detect early, affects amount parsing) ─────────
        if re.search(r"\bUSD\b|\bUS\s*\$|\bUS\s*Dollar", text, re.IGNORECASE):
            result["moneda"] = "USD"
        elif re.search(r"\bEUR\b|€|\bEuro\b", text, re.IGNORECASE):
            result["moneda"] = "EUR"
        elif re.search(r"\bGBP\b|£|\bPound\s*Sterling", text, re.IGNORECASE):
            result["moneda"] = "GBP"
        elif re.search(r"\bCAD\b|\bCanadian\s*Dollar", text, re.IGNORECASE):
            result["moneda"] = "CAD"
        elif re.search(r"\bCHF\b|\bSwiss\s*Franc", text, re.IGNORECASE):
            result["moneda"] = "CHF"
        elif re.search(r"\$", text) and not re.search(r"\bMXN\b|\bpeso", text, re.IGNORECASE):
            result["moneda"] = "USD"  # $ without MXN context → USD

        # ── Total amount (find the grand total, not subtotals) ──────
        amount_patterns = [
            # Specific "grand total" / "balance due" / "amount due" (most specific)
            r"(?:Grand\s*Total|Amount\s*Due|Balance\s*Due|Total\s*Due|Total\s*a\s*Pagar|Importe\s*Total)\s*[:\s]*[€$£]?\s*([\d.,]+)",
            # "Total" (not Subtotal) at end of document (reverse search — last match wins)
            r"(?<![Ss]ub)\bTotal\s*[:\s]*[€$£]?\s*([\d.,]+)",
            # Amount with currency symbol/code
            r"(?<![Ss]ub)\b(?:Total|Amount)\s*[:\s]*(?:USD|EUR|GBP|CAD)?\s*[€$£]?\s*([\d.,]+)",
        ]
        # For "Total", prefer the LAST occurrence (usually the grand total)
        best_total = None
        for pat in amount_patterns:
            matches = list(re.finditer(pat, text, re.IGNORECASE))
            if matches:
                # Use last match for "Total" (grand total usually at bottom)
                raw = matches[-1].group(1)
                val = _parse_amount(raw)
                if val and val > 0:
                    if best_total is None or (pat == amount_patterns[0]):
                        best_total = val
                        break
        if best_total:
            result["monto_original"] = best_total

        # ── Company name ────────────────────────────────────────────
        # The company name is almost always the FIRST line of the PDF
        # (the sender/issuer puts their name at the top).

        # Strategy 1: "Invoice from X" / "Bill From: X" (explicit label)
        from_m = re.search(
            r"(?:Invoice\s+from|Bill\s*From|Billed?\s*By|Issued\s*By|Seller|Emisor|Proveedor)\s*[:\s]+(.+)",
            text, re.IGNORECASE,
        )
        if from_m:
            name = re.split(r"\s{2,}|\t|\|", from_m.group(1).strip())[0].strip()
            if 2 < len(name) < 120 and not re.match(r"^\d", name):
                result["empresa"] = name

        # Strategy 2: First line of the document (most common — company name at top)
        _MONTH_NAMES_RE = re.compile(
            r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December|"
            r"Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\b", re.IGNORECASE,
        )
        # Detect "Bill To" / "Billed To" zone — lines after this are the BUYER, not the seller
        _BILL_TO_RE = re.compile(r"^(?:Bill\s*To|Billed?\s*To|Sold\s*To|Ship\s*To|Purchaser|Customer|Comprador|Cliente)\b", re.IGNORECASE)
        _SELLER_RE = re.compile(r"^(?:Seller|From|Bill\s*From|Billed?\s*By|Issued\s*By|Vendor|Emisor|Proveedor)\b", re.IGNORECASE)
        if not result["empresa"]:
            in_bill_to = False
            after_email = 0  # count lines after an email (likely buyer info)
            for line in lines[:20]:
                # Track bill-to / seller sections
                if _BILL_TO_RE.match(line):
                    in_bill_to = True
                    continue
                if _SELLER_RE.match(line):
                    in_bill_to = False
                    after_email = 0
                    continue
                # Skip blank separator lines that might end the bill-to zone
                if in_bill_to:
                    # Country names or short location lines end the zone
                    if re.match(r"^[A-Z]{2,}$", line) and len(line) <= 30:
                        in_bill_to = False
                    continue
                # After an email line, skip 1-2 lines (likely buyer name + country)
                if after_email > 0:
                    after_email -= 1
                    # ALL-CAPS country name ends the post-email skip zone
                    if re.match(r"^[A-Z]{2,}$", line) and len(line) <= 30:
                        after_email = 0
                    continue
                if len(line) < 2 or len(line) > 120:
                    continue
                if _SKIP_HEADER_RE.match(line):
                    continue
                # Skip lines that are just numbers/dates
                if re.match(r"^[\d\s\-/\.\,\(\):]+$", line):
                    continue
                # Skip date-range lines: "February 24th 2026 to March 23rd 2026"
                month_hits = _MONTH_NAMES_RE.findall(line)
                if len(month_hits) >= 2:
                    continue
                # Skip lines that are a date with some label: "Issued at: 2026-02-17"
                if re.search(r"\d{4}-\d{2}-\d{2}", line) and len(line) < 60:
                    continue
                # Skip lines with "Paid", "In Full", date references
                if re.match(r"^(?:Paid|Issued|Order|Status|Account|Billing|Period|Statement|Receipt)\b", line, re.IGNORECASE):
                    continue
                # Skip lines containing email addresses or URLs
                if "@" in line:
                    after_email = 2  # skip next 1-2 lines (buyer name + country)
                    continue
                if re.search(r"https?://|www\.", line, re.IGNORECASE):
                    continue
                # Skip address lines (start with number + street name)
                if re.match(r"^\d+\s+\w+\s+(St|Ave|Blvd|Dr|Road|Rd|Lane|Ln|Way|Calle|Av|Col)\b", line, re.IGNORECASE):
                    continue
                # Skip lines that look like dates: "Month Nth, YYYY", "YYYY-MM-DD", etc.
                if re.match(r"^\w+\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4}", line, re.IGNORECASE):
                    continue
                # Skip lines that contain a month name + year (likely date/period info)
                if _MONTH_NAMES_RE.search(line) and re.search(r"\d{4}", line):
                    continue
                result["empresa"] = line
                break

        # Strategy 3: Line containing a company suffix (Inc., LLC, GmbH, etc.)
        if not result["empresa"]:
            for line in lines[:15]:
                if _COMPANY_SUFFIXES.search(line):
                    name = re.sub(r"^[\d\.\)\-]+\s*", "", line).strip()
                    if 3 < len(name) < 120:
                        result["empresa"] = name
                        break

        # Clean empresa: strip trailing INVOICE / RECEIPT / FACTURA labels
        if result["empresa"]:
            result["empresa"] = re.sub(
                r"\s*[-–|]\s*(?:INVOICE|RECEIPT|FACTURA|RECHNUNG|BILL|NOTA)\s*$",
                "", result["empresa"], flags=re.IGNORECASE,
            ).strip()
            result["empresa"] = re.sub(
                r"\s+(?:INVOICE|RECEIPT|FACTURA|RECHNUNG|BILL|NOTA)\s*$",
                "", result["empresa"], flags=re.IGNORECASE,
            ).strip()

        # ── Tax ID ──────────────────────────────────────────────────
        tax_patterns = [
            r"(?:Tax\s*ID|EIN|VAT\s*(?:No\.?|Number|ID)?|TIN|RFC|GST\s*(?:No\.?)?|ABN|NIF|CIF|GSTIN|Tax\s*Number|Tax\s*Reg)\s*[:\s#]*([A-Za-z0-9][\w\-\.]{3,25})",
            r"(?:Tax\s*Registration)\s*[:\s]*([A-Za-z0-9][\w\-\.]{3,25})",
        ]
        for pat in tax_patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                result["tax_id"] = m.group(1).strip()
                break

        # ── Products / line items ───────────────────────────────────
        # Priority 1: pdfplumber tables (most reliable for structured invoices)
        table_items = _extract_amounts_from_tables(tables or [])
        if table_items:
            result["productos"] = [it["descripcion"] for it in table_items if it.get("descripcion")]
            if not result["monto_original"]:
                table_sum = sum(it.get("monto") or 0 for it in table_items)
                if table_sum > 0:
                    result["monto_original"] = table_sum

        # Priority 2: Text-based extraction — find items section
        # Detect the start of the items section by looking for table headers
        _ITEM_HEADER_RE = re.compile(
            r"^(?:Description|Items?\b|Item\s*Description|Line\s*Items?|Services?|"
            r"Concepto|Descripción|Descripcion|Productos?|Detalle|Partida|"
            r"Service\s*Description|Product\s*Name|Product|"
            r"#\s+Description|#\s+Item|No\.\s+Description)",
            re.IGNORECASE,
        )
        _TABLE_COL_WORDS = {
            "qty", "quantity", "rate", "price", "amount", "unit", "total",
            "hrs", "hours", "cantidad", "precio", "monto", "importe",
            "menge", "preis", "betrag", "#", "no", "no.",
        }
        _ITEMS_END_RE = re.compile(
            r"^(?:Subtotal|Sub\s*Total|Total|Tax|IVA|VAT|Discount|Descuento|"
            r"Shipping|Envío|Notes?|Terms|Payment|Thank|Gracias|Bank|IBAN|SWIFT)\b",
            re.IGNORECASE,
        )

        def _clean_item_desc(raw: str) -> str:
            """Strip trailing qty/rate/amount numbers from an item description line."""
            s = raw
            for _ in range(8):
                prev = s
                # $1,234.56 or €1.234,56
                s = re.sub(r"\s+[\$€£][\d,\.]+\s*$", "", s).strip()
                # 1,234.56 or 1234.56 (bare amounts)
                s = re.sub(r"\s+[\d,]+\.\d{2}\s*$", "", s).strip()
                # Bare integers (qty)
                s = re.sub(r"\s+\d{1,4}\s*$", "", s).strip()
                # "40 hrs" / "2 units" / "500 GB"
                s = re.sub(r"\s+\d{1,6}\s+(?:hrs?|units?|pcs?|ea|GB|TB|MB|KB)\s*$", "", s, flags=re.IGNORECASE).strip()
                # "x 2" or "x2"
                s = re.sub(r"\s+x\s*\d+\s*$", "", s, flags=re.IGNORECASE).strip()
                # Period/date fragments like "Jan 2026"
                s = re.sub(r"\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+\d{4}\s*$", "", s, flags=re.IGNORECASE).strip()
                if s == prev:
                    break
            return s

        if not result["productos"]:
            in_items = False
            items_collected = []
            for line in lines:
                # Detect items section start
                if _ITEM_HEADER_RE.match(line):
                    in_items = True
                    continue
                if not in_items:
                    continue
                # Detect items section end
                if _ITEMS_END_RE.match(line):
                    break
                # Skip empty / tiny lines
                if len(line) < 3:
                    continue
                # Split on wide spaces/tabs to get columns
                parts = re.split(r"\s{2,}|\t", line)
                desc_part = parts[0].strip() if parts else ""
                if not desc_part or len(desc_part) < 2:
                    continue
                # Skip lines that are only numbers/currency
                if re.match(r"^[\d\$€£\.,\s\-]+$", desc_part):
                    continue
                # Skip sub-header rows (all words are column header words)
                words = [w.lower().rstrip(".") for w in desc_part.split()]
                if words and all(w in _TABLE_COL_WORDS for w in words):
                    continue
                # Clean trailing numeric columns
                desc_clean = _clean_item_desc(desc_part)
                if desc_clean and len(desc_clean) > 2:
                    items_collected.append(desc_clean)
            if items_collected:
                result["productos"] = items_collected[:10]

        # Priority 3: Single labeled description (no table/list)
        # e.g. "Item: Cloud Hosting Service" or "For: Website Development"
        if not result["productos"]:
            for pat in [
                r"(?:Item|Product|Service|Concept|Concepto)\s*[:\s]+([^\n]{5,})",
                r"(?:Detalle|Partida|Línea)\s*[:\s]+([^\n]{5,})",
            ]:
                m = re.search(pat, text, re.IGNORECASE)
                if m:
                    desc = _clean_item_desc(m.group(1).strip())
                    if desc and len(desc) > 3:
                        result["productos"] = [desc[:200]]
                        break

        # ── Description (build from products or labeled section) ────
        if result["productos"]:
            result["descripcion"] = "; ".join(result["productos"])[:200]
        else:
            desc_patterns = [
                r"(?:Description|Service|Concept|Descripción|Concepto|Memo|Notes?|Subject|Regarding|Re:)\s*[:\s]*\n?\s*(.+)",
                r"(?:For|Por)\s*[:\s]+(.{10,})",
            ]
            for pat in desc_patterns:
                m = re.search(pat, text, re.IGNORECASE)
                if m:
                    desc = m.group(1).strip()
                    desc = re.split(r"\s{2,}|\t", desc)[0].strip()
                    if len(desc) > 3:
                        result["descripcion"] = desc[:200]
                        break

        # ── Country ─────────────────────────────────────────────────
        for name, code in _COUNTRY_MAP.items():
            if re.search(r"\b" + re.escape(name) + r"\b", text, re.IGNORECASE):
                result["pais"] = code
                break
        # Detect from state abbreviations (US)
        if not result["pais"] and re.search(r"\b(?:CA|NY|TX|FL|IL|WA|MA|PA|OH|GA|NC|NJ|VA|AZ|CO|TN)\s+\d{5}", text):
            result["pais"] = "US"

        # ── Payment method ──────────────────────────────────────────
        pay_text = text.lower()
        if "swift" in pay_text or "wire transfer" in pay_text or "bank transfer" in pay_text or "transferencia" in pay_text:
            result["forma_pago"] = "SWIFT"
        elif "paypal" in pay_text:
            result["forma_pago"] = "PayPal"
        elif "wise" in pay_text or "transferwise" in pay_text:
            result["forma_pago"] = "Wise"
        elif "stripe" in pay_text:
            result["forma_pago"] = "Stripe"
        elif "payoneer" in pay_text:
            result["forma_pago"] = "Payoneer"
        elif re.search(r"\bcredit\s*card|tarjeta|visa|mastercard|amex", pay_text):
            result["forma_pago"] = "CREDITO"

        # ── Type (INGRESO vs GASTO) ─────────────────────────────────
        # Foreign invoices uploaded by the user are almost always GASTOS
        # (subscriptions, services they paid for). INGRESO only if the user
        # is clearly the SELLER (e.g. "Invoice from [user's company]").
        # "Bill To" means the user is being billed → GASTO, not INGRESO.
        result["tipo"] = "GASTO"

        return result



