"""Quick invoice bootstrap — loads clients, products, catalogs for the Quick Invoice widget."""
import logging

from fastapi import Depends, HTTPException

from database import db, table_exists
from routers.api._helpers import _load_bootstrap_catalogs
from routers.deps import get_portal_issuer
from services.http import ok

logger = logging.getLogger(__name__)


def register_invoices_bootstrap_routes(router):
    """Register quick invoice bootstrap route."""

    @router.get("/quick-invoice/bootstrap")
    def api_quick_invoice_bootstrap(issuer: dict = Depends(get_portal_issuer)):
        """Devuelve clientes, productos, defaults y catalogos para el widget Factura rapida en Inicio."""
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
            # Plan usage for badge
            plan_usage = None
            try:
                from services.billing.plans import check_limit
                usage_info = check_limit(issuer_id=issuer_id, action="invoice")
                plan_usage = {
                    "current": usage_info.get("usage", 0),
                    "limit": usage_info.get("limit", 0),
                    "plan": usage_info.get("plan", "free"),
                    "allowed": usage_info.get("allowed", True),
                }
            except Exception:
                pass
            payload = {
                "clients": clients,
                "products": products,
                "plan_usage": plan_usage,
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
            raise HTTPException(status_code=500, detail="Error al cargar datos para factura rapida.")
