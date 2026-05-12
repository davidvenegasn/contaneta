"""Account API routes."""
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


def register_account_routes(router):
    """Register Account routes on the API router."""

    # ----- Account status (checklist activación + P36 chips topbar) -----
    @router.get("/account/status")
    def api_account_status(request: Request, issuer: dict = Depends(get_portal_issuer)):
        """
        Estado de activación del emisor para el checklist del dropdown "Mi cuenta" y chips del topbar.
        Requiere sesión o token (get_portal_issuer).
        Retorna: issuer_ok, sat_ok, has_customer, has_product, completed, total,
                 sat_status, last_sync_at, sync_status, plan_label (P36).
        """
        from services.tenant import require_issuer_id

        issuer_id = require_issuer_id(issuer)
        user_id = getattr(request.state, "user_id", 0) or 0
        issuer_ok = False
        sat_ok = False
        has_customer = False
        has_product = False
        sat_status = "none"
        last_sync_at = None
        sync_status = "ok"
        plan_label = None

        if issuer_id > 0:
            # 1) Datos fiscales: RFC, razón social, régimen no vacíos (CP opcional si existe en DB)
            ir = db_rows(
                "SELECT rfc, razon_social, regimen_fiscal FROM issuers WHERE id = ? LIMIT 1",
                (issuer_id,),
            )
            if ir:
                r = ir[0]
                rfc = (r.get("rfc") or "").strip()
                razon = (r.get("razon_social") or "").strip()
                regimen = (r.get("regimen_fiscal") or "").strip()
                issuer_ok = bool(rfc and razon and regimen)

            # 2) SAT FIEL: credenciales válidas (validation_ok = 1); P36 sat_status: ok / none / error
            sc_valid = db_rows(
                "SELECT 1 FROM sat_credentials WHERE issuer_id = ? AND validation_ok = 1 LIMIT 1",
                (issuer_id,),
            )
            sc_any = db_rows(
                "SELECT 1 FROM sat_credentials WHERE issuer_id = ? LIMIT 1",
                (issuer_id,),
            )
            sat_ok = bool(sc_valid)
            if sc_valid:
                sat_status = "ok"
            elif sc_any:
                sat_status = "error"
            else:
                sat_status = "none"

            # 3) Al menos un cliente
            cust = db_rows("SELECT COUNT(*) AS n FROM customer_profiles WHERE issuer_id = ?", (issuer_id,))
            has_customer = (cust[0]["n"] if cust else 0) >= 1

            # 4) Al menos un producto
            prod = db_rows("SELECT COUNT(*) AS n FROM issuer_products WHERE issuer_id = ?", (issuer_id,))
            has_product = (prod[0]["n"] if prod else 0) >= 1

            # P36: sync status (shared logic from services.sat.sat_sync)
            from services.sat.sat_sync import get_sat_sync_status
            _sync = get_sat_sync_status(issuer_id)
            last_sync_at = _sync["last_sync_at"]
            sync_status = _sync["status"]

            # P36: plan_label — use canonical plan from plans service for consistency
            from services.billing.plans import get_issuer_plan, get_plan_config
            _plan_name = get_issuer_plan(issuer_id)
            _plan_cfg = get_plan_config(_plan_name)
            trial_days_left = None
            if _plan_name == "free":
                # For free plan, show Trial if trial active, else hide badge
                if subscription_service.is_issuer_trial_active(issuer_id):
                    plan_label = "Trial"
                    # Calculate days remaining
                    _trial_row = db_rows(
                        "SELECT trial_expires_at FROM issuers WHERE id = ? LIMIT 1",
                        (issuer_id,),
                    )
                    if _trial_row and _trial_row[0].get("trial_expires_at"):
                        from datetime import datetime, timezone
                        try:
                            _exp = datetime.fromisoformat(_trial_row[0]["trial_expires_at"].replace("Z", "+00:00"))
                            if _exp.tzinfo is None:
                                _exp = _exp.replace(tzinfo=timezone.utc)
                            _now = datetime.now(timezone.utc)
                            trial_days_left = max(0, (_exp - _now).days)
                        except Exception:
                            pass
                else:
                    plan_label = "Gratis"
            else:
                plan_label = _plan_cfg["label"]

        completed = sum([issuer_ok, sat_ok, has_customer, has_product])
        return {
            "issuer_ok": issuer_ok,
            "sat_ok": sat_ok,
            "has_customer": has_customer,
            "has_product": has_product,
            "completed": completed,
            "total": 4,
            "sat_status": sat_status,
            "last_sync_at": last_sync_at,
            "sync_status": sync_status,
            "plan_label": plan_label,
            "trial_days_left": trial_days_left,
        }


    # ----- Global search -----

    @router.get("/jobs")
    def api_jobs(
        issuer: dict = Depends(get_portal_issuer),
        limit: int = Query(20, ge=1, le=200, description="Máximo de registros"),
    ):
        items = jobs_service.list_jobs(issuer["id"], limit=limit)
        total = jobs_service.count_jobs(issuer["id"])
        return ok_list(items, total=total)


    @router.get("/jobs/{job_id}")
    def api_job_get(job_id: int, issuer: dict = Depends(get_portal_issuer)):
        job = jobs_service.get_job_for_issuer(job_id, issuer["id"])
        if not job:
            raise HTTPException(status_code=404, detail="Job no encontrado.")
        payload = {
            "id": job.get("id"),
            "issuer_id": job.get("issuer_id"),
            "name": job.get("name"),
            "status": job.get("status"),
            "progress": job.get("progress"),
            "message": job.get("message"),
            "payload": job.get("payload"),
            "result": job.get("result"),
            "created_at": job.get("created_at"),
            "updated_at": job.get("updated_at"),
        }
        return ok(payload)

