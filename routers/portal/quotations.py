"""Portal quotations routes."""
import hashlib
import io
import json
import logging
import os
import re
import secrets
import stat
from datetime import date, datetime, timezone
from typing import Any, Optional

from fastapi import Body, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response

from config import (
    BASE_DIR,
    COOKIE_DEMO_VIEW,
    DB_PATH,
    DEV_MODE,
    PORTAL_SHELL_V2,
    REGIMEN_CODE_DESCRIPTIONS,
    REGIMEN_LABEL_TO_CODE,
)
from database import db, db_rows, has_column, table_exists
from routers.deps import get_portal_issuer
from routers.portal._helpers import (
    MAX_LIST_OFFSET,
    MESES_ES,
    _db_row_to_dict,
    _get_cfdi_by_uuid,
    _safe_abs_path,
    _strip_date_from_description,
    render_portal,
    ym_now,
)
from services import audit, file_access_log
from services import quotations as quotations_service
from services.action_log import log_action
from services.auth import csrf as csrf_service
from services.auth import rate_limit as rate_limit_service
from services.auth import session as session_service
from services.bank.bank_accounts import create_account as bank_create_account
from services.bank.bank_accounts import delete_account as bank_delete_account
from services.bank.bank_accounts import get_account as bank_get_account
from services.bank.bank_accounts import list_active_accounts as bank_list_accounts
from services.bank.bank_accounts import list_active_accounts_raw as bank_list_accounts_raw
from services.bank.bank_accounts import list_all_accounts as bank_list_all_accounts
from services.bank.bank_accounts import update_account as bank_update_account
from services.bank.bank_cfdi_matching import confirm_match as match_confirm
from services.bank.bank_cfdi_matching import find_cfdi_candidates, save_suggested_matches
from services.bank.bank_cfdi_matching import reject_match as match_reject
from services.bank.bank_own_accounts import detect_own_account_transfer, reclassify_own_transfers_by_rfc
from services.bank.bank_parse_preview import parse_bank_pdf_to_movements_preview, reclassify_movements
from services.bank.bank_preview_models import compute_dedupe_fingerprint
from services.bank.bank_preview_pipeline import parse_bank_statement_preview
from services.bank.bank_statement_ingest import (
    commit_preview_to_db,
    extract_statement_metadata,
    ingest_bank_statement,
    validate_statement_ownership,
)
from services.billing import subscription as subscription_service
from services.errors import ExternalServiceError
from services.invoices.catalog_from_cfdi import backfill_catalog_from_existing_cfdi
from services.pdf_to_excel import convert_pdf_to_xlsx, ensure_parent_dir, get_storage_root, safe_join
from services.portal_errors import portal_error_type
from services.redirects import safe_next_url
from services.sat.sat_sync import get_month_totals, get_sat_sync_status
from services.sat.subprocess_utils import run_php
from services.ym_helpers import is_annual, sanitize_ym, shift_ym, ym_sql_filter, ym_to_label

logger = logging.getLogger(__name__)

_get_month_totals = get_month_totals
_get_sat_sync_status = get_sat_sync_status


def register_quotations_routes(router, templates):
    """Register Quotations routes on the portal router."""

    def _render_portal(request, **kwargs):
        return render_portal(templates, request, **kwargs)

    def _portal_quotations_impl(request: Request, issuer: dict):
        try:
            return _render_portal(
                request,
                issuer=issuer,
                template_name="portal_quotations.html",
                active_page="quotations",
                title="Cotizaciones",
            )
        except Exception:
            logger.exception("portal: error renderizando cotizaciones")
            raise

    @router.get("/quotations", response_class=HTMLResponse)
    @router.get("/cotizaciones", response_class=HTMLResponse)
    def portal_quotations(request: Request, issuer: dict = Depends(get_portal_issuer)):
        return _portal_quotations_impl(request, issuer)

    @router.get("/cotizaciones/ping")
    def portal_cotizaciones_ping():
        return Response(content="cotizaciones-ok", media_type="text/plain")

    @router.get("/quotations/{qid}/pdf")
    def portal_quotation_pdf(
        request: Request,
        qid: int,
        issuer: dict = Depends(get_portal_issuer),
        download: str = Query("0", alias="download"),
    ):
        conn = db()
        row = conn.execute(
            "SELECT id, public_token FROM quotations WHERE issuer_id = ? AND id = ?",
            (issuer["id"], qid),
        ).fetchone()
        if not row:
            conn.close()
            raise HTTPException(status_code=404, detail="Cotización no encontrada")
        conn.close()
        quote = quotations_service.get_quotation_by_public_token(dict(row)["public_token"])
        if not quote:
            raise HTTPException(status_code=404, detail="Cotización no encontrada")
        cookie_val = request.cookies.get(session_service.get_session_cookie_name())
        data = session_service.verify_session(cookie_val)
        uid = data[0] if data and len(data) >= 1 else None
        audit.log(action="quotation_pdf", user_id=uid, issuer_id=issuer["id"], details=f"qid={qid}")
        log_action(request, "quotation_pdf", issuer_id=issuer["id"], quotation_id=qid)
        try:
            pdf_bytes = quotations_service.build_quotation_pdf(quote)
        except Exception:
            logger.exception("portal: error generando PDF de cotización qid=%s", qid)
            raise
        disposition = "attachment" if download == "1" else "inline"
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'{disposition}; filename="cotizacion-{qid}.pdf"'},
        )

    @router.get("/quotations/{qid}", response_class=HTMLResponse)
    def portal_quotation_detail(request: Request, qid: int, issuer: dict = Depends(get_portal_issuer)):
        conn = db()
        row = conn.execute(
            "SELECT id, public_token, folio, customer_rfc, customer_legal_name, customer_email, status, notes, responded_at, created_at FROM quotations WHERE issuer_id = ? AND id = ?",
            (issuer["id"], qid),
        ).fetchone()
        conn.close()
        if not row:
            raise HTTPException(status_code=404, detail="Cotización no encontrada")
        d = dict(row)
        quote = quotations_service.get_quotation_by_public_token(d["public_token"])
        if not quote:
            raise HTTPException(status_code=404, detail="Cotización no encontrada")
        return _render_portal(
            request,
            issuer=issuer,
            template_name="quote_detail.html",
            active_page="quotations",
            title="Cotización",
            extra={"quote": quote},
        )

