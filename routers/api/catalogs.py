"""Catalogs API routes."""
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


def register_catalogs_routes(router):
    """Register Catalogs routes on the API router."""

    @router.get("/catalogs/forma_pago")
    def api_forma_pago():
        try:
            return ok(list_catalog("cfdi_40_formas_pago"))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid catalog table")
        except Exception:
            logger.warning("api catalogs forma_pago: usando fallback (catalogs.db no disponible)")
            return ok(_catalog_list(FORMA_PAGO))


    @router.get("/catalogs/metodo_pago")
    def api_metodo_pago():
        try:
            return ok(list_catalog("cfdi_40_metodos_pago"))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid catalog table")
        except Exception:
            return ok([{"key": "PUE", "label": "Pago en una sola exhibición"}, {"key": "PPD", "label": "Pago en parcialidades o diferido"}])


    @router.get("/catalogs/uso_cfdi")
    def api_uso_cfdi():
        try:
            return ok(list_catalog("cfdi_40_usos_cfdi"))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid catalog table")
        except Exception:
            logger.warning("api catalogs uso_cfdi: usando fallback (catalogs.db no disponible)")
            return ok(_catalog_list(USO_CFDI))


    @router.get("/catalogs/regimen_fiscal")
    def api_regimen_fiscal():
        try:
            return ok(list_catalog("cfdi_40_regimenes_fiscales"))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid catalog table")
        except Exception:
            logger.warning("api catalogs regimen_fiscal: usando fallback (catalogs.db no disponible)")
            reg = dict(REGIMEN_FISCAL)
            reg["616"] = "Sin obligaciones fiscales"
            return ok(_catalog_list(reg))


    @router.get("/catalogs/moneda")
    def api_moneda():
        try:
            return ok(list_catalog("cfdi_40_monedas"))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid catalog table")
        except Exception:
            logger.warning("api catalogs moneda: usando fallback (catalogs.db no disponible)")
            return ok(_catalog_list(MONEDA_FALLBACK))


    @router.get("/catalogs/prodserv")
    def api_prodserv(q: str = Query(..., min_length=1), limit: int = Query(20, ge=1, le=50)):
        try:
            return ok(search_catalog("cfdi_40_productos_servicios", q=q, limit=limit))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid catalog table")
        except Exception:
            logger.warning("api catalogs prodserv: usando fallback estático (catalogs.db no disponible)")
            q_lower = q.strip().lower()
            out = []
            for clave, desc in PRODSERV_FALLBACK:
                if q_lower in clave or q_lower in desc.lower():
                    out.append({"key": clave, "label": desc})
                    if len(out) >= limit:
                        break
            return ok(out)


    @router.get("/catalogs/unidad")
    def api_unidad(q: str = Query(..., min_length=1), limit: int = Query(20, ge=1, le=50)):
        try:
            return ok(search_catalog("cfdi_40_claves_unidades", q=q, limit=limit))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid catalog table")
        except Exception:
            logger.warning("api catalogs unidad: usando fallback (catalogs.db no disponible)")
            q_lower = q.strip().lower()
            items = [
                {"key": k, "label": v}
                for k, v in UNIDAD_FALLBACK.items()
                if q_lower in v.lower() or q_lower in k.lower()
            ]
            return ok(items[: int(limit)])


    # ---------- Month Close API ----------

