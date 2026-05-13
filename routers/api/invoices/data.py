"""Invoice data route (replacement flow pre-fill)."""
import logging

from fastapi import Depends, HTTPException, Request

from database import db
from routers.deps import get_portal_issuer
from services.http import ok

logger = logging.getLogger(__name__)


def register_invoices_data_routes(router):
    """Register invoice data route."""

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
