"""Products API routes."""
import os
import json
import logging
import re
import secrets
import time
import hashlib
from typing import Optional
from datetime import datetime
from io import BytesIO

from fastapi import Request, Body, Depends, Query, HTTPException, File, UploadFile
from fastapi.responses import JSONResponse

from database import db, db_rows, table_exists, has_column, list_catalog, search_catalog
from validators import validate_customer, validate_product
from routers.deps import get_portal_issuer
from config import BASE_DIR, DEV_FIXTURES
from routers.api._helpers import (
    _api_rate_check, _load_fixture, _get_month_totals_safe,
    DEFAULT_LIST_LIMIT, MAX_LIST_LIMIT, MAX_LIST_OFFSET, QUOTATION_STATUSES,
)

logger = logging.getLogger(__name__)

try:
    from cfdi_pdf import USO_CFDI, REGIMEN_FISCAL, FORMA_PAGO, MONEDA, CLAVE_UNIDAD
except Exception:
    USO_CFDI = {"G03": "Gastos en general", "G01": "Adquisición de mercancías", "CN01": "Nómina"}
    REGIMEN_FISCAL = {"601": "General de Ley Personas Morales", "612": "Personas Físicas con Actividades Empresariales", "616": "Sin obligaciones fiscales", "626": "Régimen Simplificado de Confianza"}
    FORMA_PAGO = {"03": "Transferencia electrónica", "01": "Efectivo", "99": "Por definir"}
    MONEDA = {"MXN": "Peso Mexicano", "USD": "Dólar Americano"}
    CLAVE_UNIDAD = {"E48": "Unidad de servicio", "EA": "Cada uno", "H87": "Pieza"}

from services.billing import subscription as subscription_service
from services.auth import csrf as csrf_service
from services.action_log import log_action
from services.http import ok, ok_list
from services.schemas import ClientCreate, ProductCreate
from services import clients_service, products_service
from services import jobs as jobs_service
from services.invoices import invoices_engine
from services.sat.sat_sync import get_month_totals as _get_month_totals_raw
from services.ym_helpers import ym_sql_filter, sanitize_ym, is_annual
from facturapi_client import create_invoice, download_invoice, cancel_invoice as facturapi_cancel, FacturapiError


def register_products_routes(router):
    """Register Products routes on the API router."""

    @router.get("/products")
    def api_products(
        issuer: dict = Depends(get_portal_issuer),
        limit: int = Query(DEFAULT_LIST_LIMIT, ge=1, le=MAX_LIST_LIMIT, description="Máximo de registros"),
        offset: int = Query(0, ge=0, le=MAX_LIST_OFFSET, description="Registros a saltar"),
    ):
        fixture = _load_fixture("products")
        if fixture is not None:
            return fixture
        try:
            issuer_id = issuer["id"]
            items, total = products_service.list_products(issuer_id, limit=limit, offset=offset)
            return ok_list(items, total=total)
        except Exception as e:
            logger.warning("api_products: %s", e, exc_info=True)
            raise HTTPException(status_code=500, detail="Error al cargar la lista de productos.")


    @router.post("/products/create")
    def api_products_create(request: Request, payload: ProductCreate = Body(...), issuer: dict = Depends(get_portal_issuer)):
        csrf_service.verify_api_csrf(request)
        try:
            description = payload.description
            product_key_raw = payload.product_key
            # product_key ya viene normalizado en el schema (split '—'), pero conservamos el raw para validar/error.
            product_key = payload.product_key
            unit_key = payload.unit_key or "E48"
            unit_price = float(payload.unit_price)
            iva_rate = float(payload.iva_rate)
            errors = validate_product(description, product_key_raw, unit_key, unit_price)
            if errors:
                raise HTTPException(status_code=400, detail="; ".join(errors))
            conn = db()
            conn.execute(
                """INSERT INTO issuer_products (issuer_id, description, product_key, unit_key, unit_price, iva_rate)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (issuer["id"], description, product_key, unit_key, unit_price, iva_rate),
            )
            conn.commit()
            rid = conn.execute("SELECT last_insert_rowid() AS rid").fetchone()["rid"]
            conn.close()
            return ok({"id": rid})
        except HTTPException:
            raise
        except Exception:
            logger.exception("api products create: issuer_id=%s", issuer.get("id"))
            raise HTTPException(
                status_code=500,
                detail="No pudimos guardar el producto. Intenta de nuevo.",
            )


    @router.post("/products/delete")
    def api_products_delete(request: Request, payload: dict = Body(...), issuer: dict = Depends(get_portal_issuer)):
        """Elimina un producto del emisor. P37: uso con modal de confirmación en el portal."""
        csrf_service.verify_api_csrf(request)
        product_id = payload.get("id") or payload.get("product_id")
        if product_id is None:
            raise HTTPException(status_code=400, detail="id o product_id es requerido.")
        try:
            product_id = int(product_id)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="id debe ser numérico.")
        issuer_id = issuer["id"]
        conn = db()
        cur = conn.execute(
            "DELETE FROM issuer_products WHERE issuer_id = ? AND id = ?",
            (issuer_id, product_id),
        )
        conn.commit()
        conn.close()
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Producto no encontrado o ya fue eliminado.")
        return ok()


    # ----- Quick invoice (Home: cliente + producto → timbrar sin salir) -----
    def _load_bootstrap_catalogs() -> dict:
        """Load SAT catalogs for bootstrap. Returns dict with regimen_fiscal, uso_cfdi, forma_pago, metodo_pago, monedas."""
        catalogs = {}
        try:
            catalogs["regimen_fiscal"] = list_catalog("cfdi_40_regimenes_fiscales")
        except Exception:
            reg = dict(REGIMEN_FISCAL)
            reg.setdefault("616", "Sin obligaciones fiscales")
            catalogs["regimen_fiscal"] = _catalog_list(reg)
        try:
            catalogs["uso_cfdi"] = list_catalog("cfdi_40_usos_cfdi")
        except Exception:
            catalogs["uso_cfdi"] = _catalog_list(USO_CFDI)
        try:
            catalogs["forma_pago"] = list_catalog("cfdi_40_formas_pago")
        except Exception:
            catalogs["forma_pago"] = _catalog_list(FORMA_PAGO)
        try:
            catalogs["metodo_pago"] = list_catalog("cfdi_40_metodos_pago")
        except Exception:
            catalogs["metodo_pago"] = [
                {"key": "PUE", "label": "Pago en una sola exhibición"},
                {"key": "PPD", "label": "Pago en parcialidades o diferido"},
            ]
        try:
            catalogs["monedas"] = list_catalog("cfdi_40_monedas")
        except Exception:
            catalogs["monedas"] = _catalog_list(MONEDA_FALLBACK)
        return catalogs


