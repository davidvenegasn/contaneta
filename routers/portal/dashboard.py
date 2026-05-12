"""Portal dashboard routes."""
import hashlib
import io
import json
import logging
import os
import re
import secrets
import stat
from datetime import datetime, date, timezone
from typing import Optional, Any

from fastapi import Request, Depends, Query, HTTPException, File, UploadFile, Form, Body
from fastapi.responses import HTMLResponse, Response, RedirectResponse, JSONResponse, FileResponse

from config import BASE_DIR, REGIMEN_LABEL_TO_CODE, REGIMEN_CODE_DESCRIPTIONS, COOKIE_DEMO_VIEW, DB_PATH, DEV_MODE, PORTAL_SHELL_V2
from database import db, db_rows, has_column, table_exists
from routers.deps import get_portal_issuer
from routers.portal._helpers import (
    render_portal, ym_now, _db_row_to_dict, _strip_date_from_description,
    _safe_abs_path, _get_cfdi_by_uuid, MESES_ES, MAX_LIST_OFFSET,
)
from services import quotations as quotations_service, audit
from services.auth import rate_limit as rate_limit_service, session as session_service, csrf as csrf_service
from services.billing import subscription as subscription_service
from services import file_access_log
from services.action_log import log_action
from services.redirects import safe_next_url
from services.portal_errors import portal_error_type
from services.pdf_to_excel import convert_pdf_to_xlsx, get_storage_root, safe_join, ensure_parent_dir
from services.bank.bank_parse_preview import parse_bank_pdf_to_movements_preview, reclassify_movements
from services.bank.bank_preview_pipeline import parse_bank_statement_preview
from services.bank.bank_preview_models import compute_dedupe_fingerprint
from services.invoices.catalog_from_cfdi import backfill_catalog_from_existing_cfdi
from services.bank.bank_accounts import list_active_accounts as bank_list_accounts, list_active_accounts_raw as bank_list_accounts_raw, list_all_accounts as bank_list_all_accounts, get_account as bank_get_account, create_account as bank_create_account, update_account as bank_update_account, delete_account as bank_delete_account
from services.bank.bank_own_accounts import detect_own_account_transfer, reclassify_own_transfers_by_rfc
from services.bank.bank_statement_ingest import ingest_bank_statement, extract_statement_metadata, validate_statement_ownership, commit_preview_to_db
from services.bank.bank_cfdi_matching import find_cfdi_candidates, save_suggested_matches, confirm_match as match_confirm, reject_match as match_reject
from services.sat.sat_sync import get_sat_sync_status, get_month_totals
from services.ym_helpers import ym_sql_filter, ym_to_label, shift_ym, is_annual, sanitize_ym
from services.errors import ExternalServiceError
from services.sat.subprocess_utils import run_php

logger = logging.getLogger(__name__)

_get_month_totals = get_month_totals
_get_sat_sync_status = get_sat_sync_status


def register_dashboard_routes(router, templates):
    """Register Dashboard routes on the portal router."""

    def _render_portal(request, **kwargs):
        return render_portal(templates, request, **kwargs)

    @router.get("")
    def portal_root():
        return RedirectResponse(url="/portal/home", status_code=302)

    @router.get("/login", response_class=RedirectResponse)
    def portal_login_redirect():
        """La ruta de login es /login, no /portal/login. Redirigir para evitar 404."""
        return RedirectResponse(url="/login", status_code=302)

    @router.get("/set-demo-view", response_class=RedirectResponse)
    def portal_set_demo_view(request: Request, _: dict = Depends(get_portal_issuer)):
        resp = RedirectResponse(url="/portal/home", status_code=302)
        resp.set_cookie(COOKIE_DEMO_VIEW, "1", max_age=86400 * 7, path="/", samesite="lax")
        return resp

    @router.get("/exit-demo-view", response_class=RedirectResponse)
    def portal_exit_demo_view(request: Request):
        resp = RedirectResponse(url="/portal/home", status_code=302)
        resp.delete_cookie(COOKIE_DEMO_VIEW, path="/")
        return resp

    @router.get("/home", response_class=HTMLResponse)
    def portal_home(request: Request, issuer: dict = Depends(get_portal_issuer), ym: str | None = Query(None)):
        try:
            issuer_id = issuer["id"]
            if not ym:
                ym = ym_now()
            ym = sanitize_ym(ym, ym_now())
            _ym_filt = ym_sql_filter(ym)
            count_issued = db_rows(
                f"""
                SELECT COUNT(*) AS n FROM sat_cfdi
                WHERE issuer_id = ? AND direction = 'issued' AND fecha_emision IS NOT NULL
                  AND {_ym_filt} AND (total IS NULL OR total >= 0.01)
                """,
                (issuer_id, ym),
            )
            count_received = db_rows(
                f"""
                SELECT COUNT(*) AS n FROM sat_cfdi
                WHERE issuer_id = ? AND direction = 'received' AND fecha_emision IS NOT NULL
                  AND {_ym_filt} AND total IS NOT NULL AND total >= 0.01
                  AND (tipo_comprobante IS NULL OR UPPER(TRIM(tipo_comprobante)) != 'N')
                """,
                (issuer_id, ym),
            )
            tot_issued = _get_month_totals(issuer_id, ym, "issued")
            tot_received = _get_month_totals(issuer_id, ym, "received")
            ingresos_sin_iva = tot_issued["total_base"]
            gastos_sin_iva = tot_received["total_base"]
            iva_retenciones = tot_issued["total_retenciones"]
            iva_recibido_neto = tot_issued["total_iva_neto"]
            iva_pagado = tot_received["total_iva"]
            activities = db_rows(
                """
                SELECT direction, fecha_emision, nombre, total, uuid FROM (
                  SELECT direction, fecha_emision, nombre_receptor AS nombre, total, uuid FROM sat_cfdi
                  WHERE issuer_id = ? AND direction = 'issued' AND fecha_emision IS NOT NULL
                    AND (total IS NULL OR total >= 0.01)
                  UNION ALL
                  SELECT direction, fecha_emision, nombre_emisor AS nombre, total, uuid FROM sat_cfdi
                  WHERE issuer_id = ? AND direction = 'received' AND fecha_emision IS NOT NULL
                    AND total IS NOT NULL AND total >= 0.01
                    AND (tipo_comprobante IS NULL OR UPPER(TRIM(tipo_comprobante)) != 'N')
                ) ORDER BY fecha_emision DESC LIMIT 50
                """,
                (issuer_id, issuer_id),
            )
            today = date.today()
            for a in activities:
                try:
                    fd = datetime.strptime((a["fecha_emision"] or "")[:10], "%Y-%m-%d").date()
                    d = (today - fd).days
                    a["time_ago"] = "Hoy" if d == 0 else "Ayer" if d == 1 else f"Hace {d} días"
                except (ValueError, TypeError):
                    a["time_ago"] = a.get("fecha_emision", "")[:10] or "-"
            # Onboarding: RFC completo, FIEL/CSD, clientes, productos (para ocultar banner cuando todo está listo)
            rfc_val = (issuer.get("rfc") or "").strip().upper()
            razon = (issuer.get("razon_social") or "").strip()
            rfc_configured = bool(rfc_val and rfc_val != "PENDIENTE" and razon)
            # FIEL validation auto-fills RFC+name, so treat it as rfc_configured too
            if not rfc_configured:
                _fiel_ok = bool(
                    db_rows("SELECT 1 FROM sat_credentials WHERE issuer_id = ? AND validation_ok = 1 LIMIT 1", (issuer_id,))
                )
                if _fiel_ok:
                    rfc_configured = True
            has_fiel = bool(
                db_rows("SELECT 1 FROM sat_credentials WHERE issuer_id = ? LIMIT 1", (issuer_id,))
            )
            cust_count = db_rows("SELECT COUNT(*) AS n FROM customer_profiles WHERE issuer_id = ?", (issuer_id,))
            prod_count = db_rows("SELECT COUNT(*) AS n FROM issuer_products WHERE issuer_id = ?", (issuer_id,))
            any_issued = db_rows(
                "SELECT 1 FROM sat_cfdi WHERE issuer_id = ? AND direction = 'issued' AND (total IS NULL OR total >= 0.01) LIMIT 1",
                (issuer_id,),
            )
            fiel_validated = has_fiel and bool(
                db_rows("SELECT 1 FROM sat_credentials WHERE issuer_id = ? AND validation_ok = 1 LIMIT 1", (issuer_id,))
            )
            onboarding = {
                "rfc_configured": rfc_configured,
                "has_fiel": has_fiel,
                "fiel_validated": fiel_validated,
                "count_customers": cust_count[0]["n"] if cust_count else 0,
                "count_products": prod_count[0]["n"] if prod_count else 0,
                "has_any_issued": bool(any_issued),
            }
            onboarding["steps"] = [
                {"key": "fiel", "label": "Conecta tus credenciales SAT (FIEL)", "done": fiel_validated, "href": "/portal/config/sat"},
            ]
            onboarding["completed"] = sum(1 for s in onboarding["steps"] if s["done"])
            onboarding["total"] = len(onboarding["steps"])
            onboarding["all_done"] = onboarding["completed"] == onboarding["total"]
            # Listas para Factura rápida (dropdowns y datos precargados)
            quick_customers = db_rows(
                """
                SELECT id, rfc, legal_name, zip, tax_system, email, alias
                FROM customer_profiles WHERE issuer_id = ? ORDER BY COALESCE(alias, ''), rfc
                """,
                (issuer_id,),
            ) or []
            quick_products = db_rows(
                """
                SELECT id, description, product_key, unit_key, unit_price, iva_rate, created_at
                FROM issuer_products WHERE issuer_id = ? ORDER BY description
                """,
                (issuer_id,),
            ) or []

            def _serialize_row(r):
                d = dict(r) if hasattr(r, "keys") else r
                out = {}
                for k, v in d.items():
                    if hasattr(v, "isoformat"):
                        out[k] = v.isoformat()
                    elif hasattr(v, "__float__") and not isinstance(v, (int, bool)):
                        try:
                            out[k] = float(v)
                        except (TypeError, ValueError):
                            out[k] = v
                    else:
                        out[k] = v
                return out

            # Escapar para incrustar en <script>: evitar que </script> en datos cierre el tag
            def _script_safe(s: str) -> str:
                return (s or "").replace("</", "<\\/")
            quick_customers_json = _script_safe(json.dumps([_serialize_row(r) for r in quick_customers]))
            quick_products_json = _script_safe(json.dumps([_serialize_row(r) for r in quick_products]))

            # KPI trend badges (vs prior month)
            prev_ym = shift_ym(ym, -1)
            next_ym = shift_ym(ym, +1)
            prev_issued = _get_month_totals(issuer_id, prev_ym, "issued")
            prev_received = _get_month_totals(issuer_id, prev_ym, "received")
            prev_ingresos = prev_issued["total_base"]
            prev_gastos = prev_received["total_base"]
            prev_iva_neto = prev_issued["total_iva_neto"]
            prev_iva_pagado = prev_received["total_iva"]

            def _pct_change(cur, prev):
                if prev is None or prev == 0:
                    return None
                try:
                    return round((cur - prev) / abs(prev) * 100)
                except (TypeError, ZeroDivisionError):
                    return None

            kpi_trends = {
                "ingresos": _pct_change(ingresos_sin_iva, prev_ingresos),
                "gastos": _pct_change(gastos_sin_iva, prev_gastos),
                "iva_neto": _pct_change(iva_recibido_neto, prev_iva_neto),
                "iva_pagado": _pct_change(iva_pagado, prev_iva_pagado),
            }

            # Month list for picker (reuse summary's GROUP BY query)
            months_issued = db_rows(
                """
                SELECT substr(fecha_emision,1,7) AS ym, count(*) AS n
                FROM sat_cfdi
                WHERE issuer_id = ? AND direction = 'issued' AND fecha_emision IS NOT NULL
                GROUP BY ym ORDER BY ym DESC
                """,
                (issuer_id,),
            )
            months_received = db_rows(
                """
                SELECT substr(fecha_emision,1,7) AS ym, count(*) AS n
                FROM sat_cfdi
                WHERE issuer_id = ? AND direction = 'received' AND fecha_emision IS NOT NULL
                GROUP BY ym ORDER BY ym DESC
                """,
                (issuer_id,),
            )
            ym_counts = {}
            for m in months_issued + months_received:
                ym_counts[m["ym"]] = ym_counts.get(m["ym"], 0) + m["n"]
            if ym not in ym_counts:
                ym_counts[ym] = 0
            months = [{"ym": y, "n": n, "label": ym_to_label(y)} for y, n in sorted(ym_counts.items(), reverse=True)]

            # Notificaciones (motor simple)
            notifications = []
            try:
                from services import notifications as notifications_service

                notifications_service.refresh_for_issuer(int(issuer_id))
                notifications = notifications_service.list_notifications(int(issuer_id), unread_only=True, limit=10) or []
            except Exception:
                notifications = []

            return _render_portal(
                request,
                issuer=issuer,
                template_name="portal_home.html",
                active_page="home",
                title="Inicio",
                extra={
                    "issuer_id": issuer_id,
                    "count_issued": count_issued[0]["n"] if count_issued else 0,
                    "count_received": count_received[0]["n"] if count_received else 0,
                    "activities": activities,
                    "ym_label": ym_to_label(ym),
                    "ym": ym,
                    "prev_ym": prev_ym,
                    "next_ym": next_ym,
                    "months": months,
                    "ingresos_sin_iva": ingresos_sin_iva,
                    "gastos_sin_iva": gastos_sin_iva,
                    "iva_recibido_neto": iva_recibido_neto,
                    "iva_retenciones": iva_retenciones,
                    "iva_pagado": iva_pagado,
                    "kpi_trends": kpi_trends,
                    "onboarding": onboarding,
                    "quick_customers": quick_customers,
                    "quick_products": quick_products,
                    "quick_customers_json": quick_customers_json,
                    "quick_products_json": quick_products_json,
                    "sat_sync_status": _get_sat_sync_status(issuer_id),
                    "has_fiel_validated": has_fiel and bool(
                        db_rows(
                            "SELECT 1 FROM sat_credentials WHERE issuer_id = ? AND validation_ok = 1 LIMIT 1",
                            (issuer_id,),
                        )
                    ),
                    "notifications": notifications,
                    "csrf_token": csrf_service.generate_csrf_token(),
                },
            )
        except Exception:
            logger.exception("portal: error renderizando home")
            raise

    @router.get("/qa", response_class=HTMLResponse)
    def portal_qa(request: Request, issuer: dict = Depends(get_portal_issuer)):
        """Página interna de QA: checks básicos y enlaces rápidos. Solo visible con DEV_MODE=1 o ENV=dev."""
        if not DEV_MODE:
            raise HTTPException(status_code=404, detail="Not Found")
        try:
            issuer_id = issuer["id"]
            ym = ym_now()
            _ym_filt = ym_sql_filter(ym)
            count_issued = db_rows(
                f"""
                SELECT COUNT(*) AS n FROM sat_cfdi
                WHERE issuer_id = ? AND direction = 'issued' AND fecha_emision IS NOT NULL
                  AND {_ym_filt} AND (total IS NULL OR total >= 0.01)
                """,
                (issuer_id, ym),
            )
            count_received = db_rows(
                f"""
                SELECT COUNT(*) AS n FROM sat_cfdi
                WHERE issuer_id = ? AND direction = 'received' AND fecha_emision IS NOT NULL
                  AND {_ym_filt} AND total IS NOT NULL AND total >= 0.01
                  AND (tipo_comprobante IS NULL OR UPPER(TRIM(tipo_comprobante)) != 'N')
                """,
                (issuer_id, ym),
            )
            sat_sync_status = _get_sat_sync_status(issuer_id)
            return _render_portal(
                request,
                issuer=issuer,
                template_name="portal_qa.html",
                active_page="home",
                title="QA (solo dev)",
                extra={
                    "ym": ym,
                    "ym_label": ym_to_label(ym),
                    "count_issued": count_issued[0]["n"] if count_issued else 0,
                    "count_received": count_received[0]["n"] if count_received else 0,
                    "sat_last_sync": sat_sync_status.get("last_sync_at"),
                    "sat_status": sat_sync_status.get("status"),
                },
            )
        except HTTPException:
            raise
        except Exception:
            logger.exception("portal: error renderizando /portal/qa")
            raise HTTPException(status_code=500, detail="Error al cargar QA")

