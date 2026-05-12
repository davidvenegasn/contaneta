"""Shared helpers for portal route modules."""
import logging
import os
import re
from datetime import datetime
from typing import Any, Optional

from fastapi import Request

from config import (
    BASE_DIR,
    DEV_MODE,
    PORTAL_SHELL_V2,
    REGIMEN_CODE_DESCRIPTIONS,
    REGIMEN_LABEL_TO_CODE,
)
from database import db, db_rows
from services.auth import csrf as csrf_service

logger = logging.getLogger(__name__)

# Paginación: evitar OFFSET enorme (degrada SQLite)
MAX_LIST_OFFSET = 50_000

MESES_ES = (
    "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
    "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
)


def ym_now():
    return datetime.now().strftime("%Y-%m")


def _db_row_to_dict(row: Any) -> dict:
    """Convierte sqlite3.Row (o cualquier fila) a dict para que .get() funcione."""
    if row is None:
        return {}
    if isinstance(row, dict):
        return row
    if hasattr(row, "keys"):
        try:
            return dict(zip(row.keys(), row))
        except Exception:
            pass
    try:
        return dict(row)
    except Exception:
        return {}


def _strip_date_from_description(desc: Optional[str]) -> str:
    """Quita prefijo de fecha de la descripción para mostrar como concepto."""
    if not desc or not isinstance(desc, str):
        return desc or ""
    s = desc.strip()
    m = re.match(r"^\d{1,2}-[A-Za-z]{3}-\d{2,4}\s*", s)
    if m:
        return s[m.end():].strip() or s
    m = re.match(r"^\d{4}-\d{2}-\d{2}\s*", s)
    if m:
        return s[m.end():].strip() or s
    m = re.match(r"^\d{1,2}/\d{1,2}/\d{2,4}\s*", s)
    if m:
        return s[m.end():].strip() or s
    return s


def _safe_abs_path(path_like: str) -> str:
    """Resolve a stored path to an absolute path under BASE_DIR (prevent path traversal)."""
    if not path_like or not (path_like or "").strip():
        raise ValueError("XML no disponible")
    p = path_like.strip()
    if not os.path.isabs(p):
        p = os.path.join(BASE_DIR, p)
    abs_p = os.path.normpath(os.path.abspath(p))
    base = os.path.abspath(BASE_DIR)
    if not abs_p.startswith(base + os.sep):
        raise ValueError("Ruta XML inválida")
    blocked = [
        os.path.join(base, "keys"),
        os.path.join(base, "storage", "credentials"),
    ]
    for b in blocked:
        b_abs = os.path.normpath(os.path.abspath(b))
        if abs_p == b_abs or abs_p.startswith(b_abs + os.sep):
            raise ValueError("Ruta XML inválida")
    return abs_p


def _get_cfdi_by_uuid(issuer_id: int, uuid: str, direction: str):
    """Obtiene un CFDI de sat_cfdi por (issuer_id, uuid)."""
    u = (uuid or "").strip()
    if not u:
        return None
    conn = db()
    row = conn.execute(
        """
        SELECT uuid, fecha_emision, rfc_emisor, nombre_emisor, rfc_receptor, nombre_receptor,
               total, moneda, tipo_comprobante, status, xml_path, xml_status,
               serie, folio, forma_pago, metodo_pago, uso_cfdi, concepto,
               subtotal, descuento, impuestos, COALESCE(retenciones, 0) AS retenciones
        FROM sat_cfdi
        WHERE issuer_id = ? AND LOWER(TRIM(uuid)) = LOWER(?) AND direction = ?
        LIMIT 1
        """,
        (issuer_id, u, direction),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def render_portal(
    templates,
    request: Request,
    *,
    issuer: dict,
    template_name: str,
    active_page: str,
    title: str,
    extra: Optional[dict] = None,
    extra_context: Optional[dict] = None,
    error: Optional[str] = None,
    status_code: int = 200,
    **template_vars: Any,
):
    """Core template renderer for all portal HTML pages. Replaces the old _render_portal closure."""
    has_nomina = False
    if issuer.get("id", 0) > 0:
        try:
            r = db_rows(
                "SELECT 1 FROM sat_cfdi WHERE issuer_id = ? AND direction = 'received' AND UPPER(TRIM(COALESCE(tipo_comprobante,''))) = 'N' LIMIT 1",
                (issuer["id"],),
            )
            has_nomina = bool(r)
        except Exception:
            pass
    regimen_label = issuer.get("regimen_fiscal") or ""
    issuer_tax_code = REGIMEN_LABEL_TO_CODE.get(regimen_label) if regimen_label else ""
    if issuer_tax_code and issuer_tax_code in REGIMEN_CODE_DESCRIPTIONS:
        regimen_label = f"{issuer_tax_code} — {REGIMEN_CODE_DESCRIPTIONS[issuer_tax_code]}"
    elif regimen_label and regimen_label in REGIMEN_CODE_DESCRIPTIONS:
        regimen_label = f"{regimen_label} — {REGIMEN_CODE_DESCRIPTIONS[regimen_label]}"
    show_welcome_popup = getattr(request.state, "issuer_is_placeholder", False) and not getattr(
        request.state, "is_demo_view", False
    )
    is_demo_view = getattr(request.state, "is_demo_view", False)
    is_impersonating = getattr(request.state, "is_impersonating", False)
    issuer_id = issuer.get("id", 0)
    menu_sat_configured = False
    menu_catalog_ok = False
    if issuer_id > 0:
        try:
            menu_sat_configured = bool(
                db_rows("SELECT 1 FROM sat_credentials WHERE issuer_id = ? AND validation_ok = 1 LIMIT 1", (issuer_id,))
            )
            cust = db_rows("SELECT COUNT(*) AS n FROM customer_profiles WHERE issuer_id = ?", (issuer_id,))
            prod = db_rows("SELECT COUNT(*) AS n FROM issuer_products WHERE issuer_id = ?", (issuer_id,))
            menu_catalog_ok = (cust[0]["n"] if cust else 0) > 0 and (prod[0]["n"] if prod else 0) > 0
        except Exception:
            pass
    path = request.url.path

    def _nav_is_active(prefix_or_list):
        if isinstance(prefix_or_list, str):
            return path.startswith(prefix_or_list)
        return any(path.startswith(p) for p in prefix_or_list)

    payload: dict[str, Any] = {
        "request": request,
        "token": "",
        "portal_issuer_id": int(issuer_id) if issuer_id else 0,
        "issuer_alias": issuer.get("alias", ""),
        "issuer_rfc": issuer.get("rfc", ""),
        "issuer_tax_system": issuer_tax_code,
        "issuer_regimen_label": regimen_label or "",
        "active_page": active_page,
        "nav_is_active": _nav_is_active,
        "title": title,
        "error": error,
        "has_nomina": has_nomina,
        "show_welcome_popup": show_welcome_popup,
        "is_demo_view": is_demo_view,
        "is_impersonating": is_impersonating,
        "menu_sat_configured": menu_sat_configured,
        "menu_catalog_ok": menu_catalog_ok,
        "dev_debug_panel": DEV_MODE,
        "portal_shell_v2": PORTAL_SHELL_V2,
    }
    if extra:
        payload.update(extra)
    if extra_context:
        payload.update(extra_context)
    if template_vars:
        payload.update(template_vars)
    payload.setdefault("csrf_token", csrf_service.generate_csrf_token())
    return templates.TemplateResponse(template_name, payload, status_code=status_code)
