"""Customers API routes."""
import hashlib
import json
import logging
import os
import re
import secrets
import time
from datetime import datetime
from io import BytesIO
from typing import Optional

from fastapi import Body, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse

from config import BASE_DIR, DEV_FIXTURES
from database import db, db_rows, has_column, list_catalog, search_catalog, table_exists
from routers.api._helpers import (
    DEFAULT_LIST_LIMIT,
    MAX_LIST_LIMIT,
    MAX_LIST_OFFSET,
    QUOTATION_STATUSES,
    _api_rate_check,
    _get_month_totals_safe,
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
from services import clients_service, products_service
from services import jobs as jobs_service
from services.action_log import log_action
from services.auth import csrf as csrf_service
from services.billing import subscription as subscription_service
from services.http import ok, ok_list
from services.invoices import invoices_engine
from services.sat.sat_sync import get_month_totals as _get_month_totals_raw
from services.schemas import ClientCreate, ProductCreate
from services.ym_helpers import is_annual, sanitize_ym, ym_sql_filter


def register_customers_routes(router):
    """Register Customers routes on the API router."""

    @router.get("/customers")
    def api_customers(
        issuer: dict = Depends(get_portal_issuer),
        limit: int = Query(DEFAULT_LIST_LIMIT, ge=1, le=MAX_LIST_LIMIT, description="Máximo de registros"),
        offset: int = Query(0, ge=0, le=MAX_LIST_OFFSET, description="Registros a saltar"),
    ):
        fixture = _load_fixture("clients")
        if fixture is not None:
            return fixture
        try:
            conn = db()
            issuer_id = issuer["id"]
            # Incluir clientes que están en la tabla "clients" (p. ej. backfill desde facturas emitidas)
            # para que el dropdown de factura rápida muestre los mismos que la página Contactos > Clientes.
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
            conn.close()
            items, total = clients_service.list_clients(issuer_id, limit=limit, offset=offset)
            return ok_list(items, total=total)
        except Exception as e:
            logger.warning("api_customers: %s", e, exc_info=True)
            raise HTTPException(status_code=500, detail="Error al cargar la lista de clientes.")


    @router.post("/customers/create")
    def api_customers_create(request: Request, payload: ClientCreate = Body(...), issuer: dict = Depends(get_portal_issuer)):
        csrf_service.verify_api_csrf(request)
        try:
            rfc = payload.rfc
            legal_name = payload.legal_name
            zip_val = payload.zip or ""
            tax_val = payload.tax_system or ""
            email = payload.email or None
            alias = payload.alias or None
            errors = validate_customer(rfc, legal_name, zip_val, tax_val, email)
            if errors:
                raise HTTPException(status_code=400, detail="; ".join(errors))
            conn = db()
            conn.execute(
                """
                INSERT INTO customer_profiles (issuer_id, rfc, legal_name, zip, tax_system, email, alias, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(issuer_id, rfc) DO UPDATE SET
                    legal_name = excluded.legal_name, zip = excluded.zip, tax_system = excluded.tax_system,
                    email = excluded.email, alias = excluded.alias, updated_at = CURRENT_TIMESTAMP
                """,
                (issuer["id"], rfc, legal_name, zip_val, tax_val, email, alias),
            )
            conn.commit()
            conn.close()
            return ok({"rfc": rfc})
        except HTTPException:
            raise
        except Exception:
            logger.exception("api customers create: issuer_id=%s", issuer.get("id"))
            raise HTTPException(
                status_code=500,
                detail="No pudimos guardar el cliente. Intenta de nuevo.",
            )


    @router.post("/customers/delete")
    def api_customers_delete(request: Request, payload: dict = Body(...), issuer: dict = Depends(get_portal_issuer)):
        csrf_service.verify_api_csrf(request)
        try:
            rfc = (payload.get("rfc") or "").strip().upper()
            if not rfc:
                raise HTTPException(status_code=400, detail="RFC requerido")
            conn = db()
            cur = conn.execute("DELETE FROM customer_profiles WHERE issuer_id = ? AND rfc = ?", (issuer["id"], rfc))
            conn.commit()
            conn.close()
            if cur.rowcount == 0:
                raise HTTPException(status_code=404, detail="Cliente no encontrado")
            return ok({"rfc": rfc})
        except HTTPException:
            raise
        except Exception:
            logger.exception("api customers delete: issuer_id=%s", issuer.get("id"))
            raise HTTPException(
                status_code=500,
                detail="No pudimos completar la acción. Intenta de nuevo.",
            )



