# Portal HTML routes and helpers
import hashlib
import json
import logging
import os
import secrets
import stat
import subprocess
from datetime import datetime, date
from typing import Optional

from fastapi import APIRouter, Request, Depends, Query, HTTPException, File, UploadFile, Form, Body
from fastapi.responses import HTMLResponse, Response, RedirectResponse, JSONResponse, FileResponse

from config import BASE_DIR, REGIMEN_LABEL_TO_CODE, COOKIE_DEMO_VIEW, DB_PATH, DEV_MODE
from database import db, db_rows, has_column
from routers.deps import get_portal_issuer
from services import quotations as quotations_service, rate_limit as rate_limit_service, session as session_service, audit, subscription as subscription_service, csrf as csrf_service
from services.action_log import log_action
from services.pdf_to_excel import convert_pdf_to_xlsx, get_storage_root, safe_join, ensure_parent_dir
from services.catalog_from_cfdi import backfill_catalog_from_existing_cfdi

logger = logging.getLogger(__name__)

# ----------------------------
# Helpers
# ----------------------------

MESES_ES = (
    "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
    "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"
)


def ym_now():
    return datetime.now().strftime("%Y-%m")


def _ensure_sat_credentials_validation_columns(conn) -> None:
    """Añade columnas validation_* a sat_credentials si no existen."""
    for col, col_type in [("validation_at", "TEXT"), ("validation_ok", "INTEGER"), ("validation_message", "TEXT")]:
        if not has_column(conn, "sat_credentials", col):
            conn.execute(f"ALTER TABLE sat_credentials ADD COLUMN {col} {col_type};")


def _credentials_dir(issuer_id: int) -> str:
    """Ruta al directorio storage/credentials/{issuer_id}/ (creado si no existe)."""
    path = os.path.join(BASE_DIR, "storage", "credentials", str(issuer_id))
    os.makedirs(path, mode=0o700, exist_ok=True)
    return path


def _run_fiel_validation(issuer_id: int) -> tuple[bool, str]:
    """Ejecuta check_fiel.php para issuer_id, actualiza sat_credentials y devuelve (ok, message)."""
    php_script = os.path.join(BASE_DIR, "sat_sync", "check_fiel.php")
    if not os.path.isfile(php_script):
        return False, "No se encontró el script de validación."
    env = os.environ.copy()
    env["APP_DB_PATH"] = str(DB_PATH)
    try:
        proc = subprocess.run(
            ["php", php_script, str(issuer_id)],
            cwd=BASE_DIR,
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
        )
    except subprocess.TimeoutExpired:
        return False, "Validación tardó demasiado."
    except FileNotFoundError:
        return False, "PHP no está instalado o no está en el PATH."
    stderr = (proc.stderr or "").strip()
    stdout = (proc.stdout or "").strip()
    ok = proc.returncode == 0
    message = stdout if ok else (stderr or "Error al validar la FIEL.")
    conn = db()
    try:
        _ensure_sat_credentials_validation_columns(conn)
        if has_column(conn, "sat_credentials", "validation_at"):
            conn.execute(
                """
                UPDATE sat_credentials SET validation_at = datetime('now'), validation_ok = ?, validation_message = ?
                WHERE issuer_id = ?
                """,
                (1 if ok else 0, message[:500], issuer_id),
            )
            conn.commit()
    finally:
        conn.close()
    return ok, message


def ym_to_label(ym: str) -> str:
    """Convert 2026-01 to 'Enero 2026'."""
    try:
        y, m = ym.split("-")
        return f"{MESES_ES[int(m) - 1]} {y}"
    except (ValueError, IndexError):
        return ym


def shift_ym(ym: str, delta_months: int) -> str:
    y, m = ym.split("-")
    y, m = int(y), int(m)
    m += delta_months
    while m <= 0:
        m += 12
        y -= 1
    while m >= 13:
        m -= 12
        y += 1
    return f"{y:04d}-{m:02d}"


def _get_month_totals(issuer_id: int, ym: str, direction: str) -> dict:
    """Totales del mes para emitidas o recibidas: base (subtotal), IVA y retenciones."""
    conn = db()
    try:
        base_where = (
            "issuer_id = ? AND direction = ? AND fecha_emision IS NOT NULL AND substr(fecha_emision,1,7) = ?"
        )
        if direction == "issued":
            base_where += " AND (total IS NULL OR total >= 0.01)"
        else:
            base_where += " AND total IS NOT NULL AND total >= 0.01 AND (tipo_comprobante IS NULL OR UPPER(TRIM(tipo_comprobante)) != 'N')"
        params = (issuer_id, direction, ym)
        has_retenciones = has_column(conn, "sat_cfdi", "retenciones")
        if has_retenciones:
            row = conn.execute(
                f"""
                SELECT
                    COALESCE(SUM(COALESCE(subtotal, total)), 0) AS total_base,
                    COALESCE(SUM(COALESCE(impuestos, 0)), 0) AS total_iva,
                    COALESCE(SUM(COALESCE(retenciones, 0)), 0) AS total_retenciones
                FROM sat_cfdi
                WHERE {base_where}
                """,
                params,
            ).fetchone()
        else:
            row = conn.execute(
                f"""
                SELECT
                    COALESCE(SUM(COALESCE(subtotal, total)), 0) AS total_base,
                    COALESCE(SUM(COALESCE(impuestos, 0)), 0) AS total_iva
                FROM sat_cfdi
                WHERE {base_where}
                """,
                params,
            ).fetchone()
        total_base = float(row[0] or 0) if row else 0.0
        total_iva = float(row[1] or 0) if row else 0.0
        total_retenciones = float(row[2] or 0) if (has_retenciones and row and len(row) >= 3) else 0.0
        return {
            "total_base": total_base,
            "total_iva": total_iva,
            "total_retenciones": total_retenciones,
            "total_iva_neto": max(0.0, total_iva - total_retenciones) if direction == "issued" else total_iva,
        }
    finally:
        conn.close()


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
    return abs_p


def _get_sat_sync_status(issuer_id: int) -> dict:
    """Estado del sync SAT para un issuer: last_sync_at, status (running|ok|error), message."""
    conn = db()
    try:
        running = conn.execute(
            "SELECT 1 FROM sat_jobs WHERE issuer_id = ? AND status IN ('queued','running') LIMIT 1",
            (issuer_id,),
        ).fetchone()
        last_ok = conn.execute(
            "SELECT MAX(finished_at) AS t FROM sat_jobs WHERE issuer_id = ? AND status = 'ok'",
            (issuer_id,),
        ).fetchone()
        last_error = conn.execute(
            "SELECT finished_at, last_error FROM sat_jobs WHERE issuer_id = ? AND status = 'error' ORDER BY finished_at DESC LIMIT 1",
            (issuer_id,),
        ).fetchone()
        sync_state = conn.execute(
            "SELECT MAX(last_run_at) AS t FROM sat_sync_state WHERE issuer_id = ?",
            (issuer_id,),
        ).fetchone()
    finally:
        conn.close()
    last_sync_at = (sync_state and sync_state["t"]) or (last_ok and last_ok["t"]) or None
    if running:
        status = "running"
        message = "Sincronización en proceso"
    elif last_error and last_ok and last_error["t"] and last_ok["t"] and last_error["t"] > last_ok["t"]:
        status = "error"
        message = (last_error["last_error"] or "Error en la última sincronización")[:200]
    elif last_error and not last_ok:
        status = "error"
        message = (last_error["last_error"] or "Error en la última sincronización")[:200]
    else:
        status = "ok"
        message = None
    return {"last_sync_at": last_sync_at, "status": status, "message": message}


def _get_cfdi_by_uuid(issuer_id: int, uuid: str, direction: str):
    """Obtiene un CFDI de sat_cfdi por (issuer_id, uuid). direction: 'issued' o 'received'. Búsqueda por UUID case-insensitive."""
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


def get_portal_router(templates):
    """Build portal router with all /portal/* HTML routes. Requires Jinja2 templates instance."""

    def _render_portal(
        request: Request,
        *,
        issuer: dict,
        template_name: str,
        active_page: str,
        title: str,
        extra: Optional[dict] = None,
        error: Optional[str] = None,
        status_code: int = 200,
    ):
        has_nomina = False
        if issuer.get("id", 0) > 0:
            r = db_rows(
                "SELECT 1 FROM sat_cfdi WHERE issuer_id = ? AND direction = 'received' AND UPPER(TRIM(COALESCE(tipo_comprobante,''))) = 'N' LIMIT 1",
                (issuer["id"],),
            )
            has_nomina = bool(r)
        regimen_label = issuer.get("regimen_fiscal") or ""
        issuer_tax_code = REGIMEN_LABEL_TO_CODE.get(regimen_label) if regimen_label else ""
        show_welcome_popup = getattr(request.state, "issuer_is_placeholder", False) and not getattr(
            request.state, "is_demo_view", False
        )
        is_demo_view = getattr(request.state, "is_demo_view", False)
        is_impersonating = getattr(request.state, "is_impersonating", False)
        issuer_id = issuer.get("id", 0)
        menu_sat_configured = False
        menu_catalog_ok = False
        if issuer_id > 0:
            menu_sat_configured = bool(
                db_rows("SELECT 1 FROM sat_credentials WHERE issuer_id = ? AND validation_ok = 1 LIMIT 1", (issuer_id,))
            )
            cust = db_rows("SELECT COUNT(*) AS n FROM customer_profiles WHERE issuer_id = ?", (issuer_id,))
            prod = db_rows("SELECT COUNT(*) AS n FROM issuer_products WHERE issuer_id = ?", (issuer_id,))
            menu_catalog_ok = (cust[0]["n"] if cust else 0) > 0 and (prod[0]["n"] if prod else 0) > 0
        payload = {
            "request": request,
            "token": "",
            "issuer_alias": issuer["alias"],
            "issuer_rfc": issuer["rfc"],
            "issuer_tax_system": issuer_tax_code,
            "issuer_regimen_label": regimen_label or "",
            "active_page": active_page,
            "title": title,
            "error": error,
            "has_nomina": has_nomina,
            "show_welcome_popup": show_welcome_popup,
            "is_demo_view": is_demo_view,
            "is_impersonating": is_impersonating,
            "menu_sat_configured": menu_sat_configured,
            "menu_catalog_ok": menu_catalog_ok,
            "dev_debug_panel": DEV_MODE,
        }
        if extra:
            payload.update(extra)
        payload.setdefault("csrf_token", csrf_service.generate_csrf_token())
        return templates.TemplateResponse(template_name, payload, status_code=status_code)

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

    router = APIRouter(prefix="/portal", tags=["portal"])

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

    @router.get("/home", response_class=HTMLResponse)
    def portal_home(request: Request, issuer: dict = Depends(get_portal_issuer)):
        try:
            issuer_id = issuer["id"]
            ym = ym_now()
            count_issued = db_rows(
                """
                SELECT COUNT(*) AS n FROM sat_cfdi
                WHERE issuer_id = ? AND direction = 'issued' AND fecha_emision IS NOT NULL
                  AND substr(fecha_emision,1,7) = ? AND (total IS NULL OR total >= 0.01)
                """,
                (issuer_id, ym),
            )
            count_received = db_rows(
                """
                SELECT COUNT(*) AS n FROM sat_cfdi
                WHERE issuer_id = ? AND direction = 'received' AND fecha_emision IS NOT NULL
                  AND substr(fecha_emision,1,7) = ? AND total IS NOT NULL AND total >= 0.01
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
                SELECT direction, fecha_emision, nombre FROM (
                  SELECT direction, fecha_emision, nombre_receptor AS nombre FROM sat_cfdi
                  WHERE issuer_id = ? AND direction = 'issued' AND fecha_emision IS NOT NULL
                    AND (total IS NULL OR total >= 0.01)
                  UNION ALL
                  SELECT direction, fecha_emision, nombre_emisor AS nombre FROM sat_cfdi
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
            has_fiel = bool(
                db_rows("SELECT 1 FROM sat_credentials WHERE issuer_id = ? LIMIT 1", (issuer_id,))
            )
            cust_count = db_rows("SELECT COUNT(*) AS n FROM customer_profiles WHERE issuer_id = ?", (issuer_id,))
            prod_count = db_rows("SELECT COUNT(*) AS n FROM issuer_products WHERE issuer_id = ?", (issuer_id,))
            any_issued = db_rows(
                "SELECT 1 FROM sat_cfdi WHERE issuer_id = ? AND direction = 'issued' AND (total IS NULL OR total >= 0.01) LIMIT 1",
                (issuer_id,),
            )
            onboarding = {
                "rfc_configured": rfc_configured,
                "has_fiel": has_fiel,
                "count_customers": cust_count[0]["n"] if cust_count else 0,
                "count_products": prod_count[0]["n"] if prod_count else 0,
                "has_any_issued": bool(any_issued),
            }
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
                    "ingresos_sin_iva": ingresos_sin_iva,
                    "gastos_sin_iva": gastos_sin_iva,
                    "iva_recibido_neto": iva_recibido_neto,
                    "iva_retenciones": iva_retenciones,
                    "iva_pagado": iva_pagado,
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
                },
            )
        except Exception:
            logger.exception("portal: error renderizando home")
            raise

    @router.get("/create", response_class=HTMLResponse)
    def portal_create(
        request: Request,
        issuer: dict = Depends(get_portal_issuer),
        quote_id: Optional[int] = Query(None),
        customer_rfc: Optional[str] = Query(None),
        customer_legal_name: Optional[str] = Query(None),
        customer_zip: Optional[str] = Query(None),
        customer_tax_system: Optional[str] = Query(None),
        customer_email: Optional[str] = Query(None),
        concept_desc: Optional[str] = Query(None),
        concept_key: Optional[str] = Query(None),
        concept_unit: Optional[str] = Query(None),
        concept_price: Optional[str] = Query(None),
        concept_iva: Optional[str] = Query(None),
    ):
        customer_prefill = None
        concept_prefill = None
        quote_items = None
        if quote_id is not None:
            try:
                conn = db()
                row = conn.execute(
                    "SELECT customer_rfc, customer_legal_name, customer_email FROM quotations WHERE issuer_id = ? AND id = ?",
                    (issuer["id"], quote_id),
                ).fetchone()
                if row:
                    r = dict(row)
                    customer_prefill = {
                        "customer_rfc": (r.get("customer_rfc") or "").strip(),
                        "customer_legal_name": (r.get("customer_legal_name") or "").strip(),
                        "customer_zip": "",
                        "customer_tax_system": "",
                        "customer_email": (r.get("customer_email") or "").strip(),
                    }
                    items = conn.execute(
                        "SELECT description, quantity, unit_price, iva_rate FROM quotation_items WHERE quotation_id = ? ORDER BY sort_order, id",
                        (quote_id,),
                    ).fetchall()
                    conn.close()
                    quote_items = [
                        {
                            "description": x["description"],
                            "quantity": float(x["quantity"] or 0),
                            "unit_price": float(x["unit_price"] or 0),
                            "iva_rate": float(x["iva_rate"] or 0.16),
                        }
                        for x in items
                    ]
                    if quote_items:
                        concept_prefill = {
                            "description": quote_items[0]["description"],
                            "product_key": "",
                            "unit_key": "E48",
                            "unit_price": str(quote_items[0]["unit_price"]),
                            "iva_rate": str(quote_items[0]["iva_rate"]),
                        }
                else:
                    conn.close()
            except ValueError:
                pass
        if customer_prefill is None and (customer_rfc or customer_legal_name or customer_zip or customer_tax_system or customer_email):
            customer_prefill = {
                "customer_rfc": (customer_rfc or "").strip(),
                "customer_legal_name": (customer_legal_name or "").strip(),
                "customer_zip": (customer_zip or "").strip(),
                "customer_tax_system": (customer_tax_system or "").strip(),
                "customer_email": (customer_email or "").strip(),
            }
        if concept_prefill is None and (concept_desc or concept_key or concept_unit or concept_price or concept_iva):
            concept_prefill = {
                "description": (concept_desc or "").strip(),
                "product_key": (concept_key or "").strip(),
                "unit_key": (concept_unit or "").strip() or "E48",
                "unit_price": (concept_price or "").strip(),
                "iva_rate": (concept_iva or "0.16").strip(),
            }
        try:
            return _render_portal(
                request,
                issuer=issuer,
                template_name="form.html",
                active_page="create",
                title="Factura nueva",
                extra={
                    "create_mode": "normal",
                    "customer_prefill": customer_prefill,
                    "concept_prefill": concept_prefill,
                    "quote_items": quote_items,
                    "csrf_token": csrf_service.generate_csrf_token(),
                },
            )
        except Exception:
            logger.exception("portal: error renderizando /portal/create")
            raise

    @router.get("/create/quick", response_class=HTMLResponse)
    def portal_create_quick(
        request: Request,
        issuer: dict = Depends(get_portal_issuer),
        customer_id: Optional[int] = Query(None),
        product_id: Optional[int] = Query(None),
    ):
        # Sin cliente y producto: página para elegir (misma fuente que Clientes y Productos: /api/customers, /api/products)
        if customer_id is None or product_id is None:
            try:
                return _render_portal(
                    request,
                    issuer=issuer,
                    template_name="portal_create_quick_choose.html",
                    active_page="create",
                    title="Factura rápida",
                )
            except Exception:
                logger.exception("portal: error renderizando selector factura rápida")
                raise
        customer_prefill = None
        concept_prefill = None
        issuer_id = issuer["id"]
        cust = db_rows(
            "SELECT id, rfc, legal_name, zip, tax_system, email FROM customer_profiles WHERE issuer_id = ? AND id = ? LIMIT 1",
            (issuer_id, customer_id),
        )
        prod = db_rows(
            "SELECT id, description, product_key, unit_key, unit_price, iva_rate FROM issuer_products WHERE issuer_id = ? AND id = ? LIMIT 1",
            (issuer_id, product_id),
        )
        if cust and prod:
            c = cust[0]
            p = prod[0]
            customer_prefill = {
                "customer_rfc": (c.get("rfc") or "").strip(),
                "customer_legal_name": (c.get("legal_name") or "").strip(),
                "customer_zip": (c.get("zip") or "").strip(),
                "customer_tax_system": (c.get("tax_system") or "").strip(),
                "customer_email": (c.get("email") or "").strip(),
            }
            concept_prefill = {
                "description": (p.get("description") or "").strip(),
                "product_key": (p.get("product_key") or "").strip(),
                "unit_key": (p.get("unit_key") or "").strip() or "E48",
                "unit_price": str(p.get("unit_price") or ""),
                "iva_rate": str(p.get("iva_rate") or "0.16"),
            }
        try:
            return _render_portal(
                request,
                issuer=issuer,
                template_name="form.html",
                active_page="create_quick",
                title="Factura rápida",
                extra={
                    "create_mode": "quick",
                    "csrf_token": csrf_service.generate_csrf_token(),
                    "customer_prefill": customer_prefill,
                    "concept_prefill": concept_prefill,
                },
            )
        except Exception:
            logger.exception("portal: error renderizando /portal/create/quick")
            raise

    @router.get("/create/multi", response_class=HTMLResponse)
    def portal_create_multi(request: Request, issuer: dict = Depends(get_portal_issuer)):
        try:
            return _render_portal(
                request, issuer=issuer, template_name="form.html", active_page="create_multi", title="Factura múltiple", extra={"create_mode": "multi", "csrf_token": csrf_service.generate_csrf_token()}
            )
        except Exception:
            logger.exception("portal: error renderizando /portal/create/multi")
            raise

    @router.get("/invoices", response_class=HTMLResponse)
    def portal_invoices(request: Request, issuer: dict = Depends(get_portal_issuer)):
        try:
            return _render_portal(
                request, issuer=issuer, template_name="portal_invoices.html", active_page="issued", title="Mis facturas"
            )
        except Exception:
            logger.exception("portal: error renderizando /portal/invoices")
            raise

    @router.get("/invoices/issued", response_class=HTMLResponse)
    def portal_invoices_issued(request: Request, issuer: dict = Depends(get_portal_issuer), ym: str = None):
        try:
            issuer_id = issuer["id"]
            if not ym:
                ym = ym_now()
            rows = db_rows("""
                SELECT uuid, fecha_emision, rfc_receptor, nombre_receptor, concepto, total, moneda,
                       COALESCE(impuestos, 0) AS impuestos, COALESCE(retenciones, 0) AS retenciones,
                       metodo_pago, status, xml_path
                FROM sat_cfdi
                WHERE issuer_id = ? AND direction = 'issued' AND fecha_emision IS NOT NULL
                  AND substr(fecha_emision,1,7) = ? AND (total IS NULL OR total >= 0.01)
                  AND xml_path IS NOT NULL AND TRIM(COALESCE(xml_path,'')) != ''
                  AND id IN (
                    SELECT id FROM (
                      SELECT id, ROW_NUMBER() OVER (
                        PARTITION BY issuer_id, direction, LOWER(TRIM(uuid))
                        ORDER BY (CASE WHEN COALESCE(total,0) >= 0.01 THEN 0 ELSE 1 END), id
                      ) AS rn
                      FROM sat_cfdi
                      WHERE issuer_id = ? AND direction = 'issued' AND fecha_emision IS NOT NULL AND substr(fecha_emision,1,7) = ? AND (total IS NULL OR total >= 0.01)
                        AND xml_path IS NOT NULL AND TRIM(COALESCE(xml_path,'')) != ''
                    ) WHERE rn = 1
                  )
                ORDER BY fecha_emision DESC LIMIT 300;
            """, (issuer_id, ym, issuer_id, ym))
            months = db_rows("""
                SELECT substr(fecha_emision,1,7) AS ym, count(*) AS n
                FROM sat_cfdi
                WHERE issuer_id = ? AND direction = 'issued' AND fecha_emision IS NOT NULL
                  AND (total IS NULL OR total >= 0.01)
                  AND xml_path IS NOT NULL AND TRIM(COALESCE(xml_path,'')) != ''
                GROUP BY ym ORDER BY ym DESC;
            """, (issuer_id,))
            for m in months:
                m["label"] = ym_to_label(m["ym"])
            month_totals = _get_month_totals(issuer_id, ym, "issued")
            return _render_portal(
                request,
                issuer=issuer,
                template_name="portal_issued.html",
                active_page="issued",
                title="Facturas emitidas",
                extra={
                    "rows": rows,
                    "ym": ym,
                    "ym_label": ym_to_label(ym),
                    "prev_ym": shift_ym(ym, -1),
                    "next_ym": shift_ym(ym, +1),
                    "months": months,
                    "month_totals": month_totals,
                    "sat_sync_status": _get_sat_sync_status(issuer_id),
                    "has_fiel_validated": bool(db_rows("SELECT 1 FROM sat_credentials WHERE issuer_id = ? AND validation_ok = 1 LIMIT 1", (issuer_id,))),
                },
            )
        except Exception:
            logger.exception("portal: error renderizando /portal/invoices/issued ym=%s", ym)
            raise

    @router.get("/invoices/received", response_class=HTMLResponse)
    def portal_invoices_received(request: Request, issuer: dict = Depends(get_portal_issuer), ym: str = None):
        try:
            issuer_id = issuer["id"]
            if not ym:
                ym = ym_now()
            rows = db_rows("""
                SELECT uuid, fecha_emision, rfc_emisor, nombre_emisor, concepto, total, moneda,
                       COALESCE(impuestos, 0) AS impuestos, COALESCE(retenciones, 0) AS retenciones,
                       metodo_pago, status, xml_path
                FROM sat_cfdi
                WHERE issuer_id = ? AND direction = 'received' AND fecha_emision IS NOT NULL
                  AND substr(fecha_emision,1,7) = ? AND total IS NOT NULL AND total >= 0.01
                  AND (tipo_comprobante IS NULL OR UPPER(TRIM(tipo_comprobante)) != 'N')
                  AND xml_path IS NOT NULL AND TRIM(COALESCE(xml_path,'')) != ''
                  AND id IN (
                    SELECT id FROM (
                      SELECT id, ROW_NUMBER() OVER (
                        PARTITION BY issuer_id, direction, LOWER(TRIM(uuid))
                        ORDER BY id
                      ) AS rn
                      FROM sat_cfdi
                      WHERE issuer_id = ? AND direction = 'received' AND fecha_emision IS NOT NULL AND substr(fecha_emision,1,7) = ? AND total IS NOT NULL AND total >= 0.01 AND (tipo_comprobante IS NULL OR UPPER(TRIM(tipo_comprobante)) != 'N')
                        AND xml_path IS NOT NULL AND TRIM(COALESCE(xml_path,'')) != ''
                    ) WHERE rn = 1
                  )
                ORDER BY fecha_emision DESC LIMIT 300;
            """, (issuer_id, ym, issuer_id, ym))
            months = db_rows("""
                SELECT substr(fecha_emision,1,7) AS ym, count(*) AS n
                FROM sat_cfdi
                WHERE issuer_id = ? AND direction = 'received' AND fecha_emision IS NOT NULL
                  AND total IS NOT NULL AND total >= 0.01
                  AND (tipo_comprobante IS NULL OR UPPER(TRIM(tipo_comprobante)) != 'N')
                  AND xml_path IS NOT NULL AND TRIM(COALESCE(xml_path,'')) != ''
                GROUP BY ym ORDER BY ym DESC;
            """, (issuer_id,))
            for m in months:
                m["label"] = ym_to_label(m["ym"])
            month_totals = _get_month_totals(issuer_id, ym, "received")
            return _render_portal(
                request,
                issuer=issuer,
                template_name="portal_received.html",
                active_page="received",
                title="Facturas recibidas",
                extra={
                    "rows": rows,
                    "ym": ym,
                    "ym_label": ym_to_label(ym),
                    "prev_ym": shift_ym(ym, -1),
                    "next_ym": shift_ym(ym, +1),
                    "months": months,
                    "month_totals": month_totals,
                    "sat_sync_status": _get_sat_sync_status(issuer_id),
                    "has_fiel_validated": bool(db_rows("SELECT 1 FROM sat_credentials WHERE issuer_id = ? AND validation_ok = 1 LIMIT 1", (issuer_id,))),
                },
            )
        except Exception:
            logger.exception("portal: error renderizando /portal/invoices/received ym=%s", ym)
            raise

    @router.get("/invoices/nomina", response_class=HTMLResponse)
    def portal_invoices_nomina(request: Request, issuer: dict = Depends(get_portal_issuer), ym: str = None):
        try:
            issuer_id = issuer["id"]
            if not ym:
                ym = ym_now()
            rows = db_rows("""
                SELECT uuid, fecha_emision, rfc_emisor, nombre_emisor, total, moneda, status, xml_path,
                       serie, folio, concepto, forma_pago, metodo_pago, uso_cfdi, subtotal, descuento, impuestos,
                       tipo_comprobante, xml_status
                FROM sat_cfdi
                WHERE issuer_id = ? AND direction = 'received'
                  AND UPPER(TRIM(COALESCE(tipo_comprobante,''))) = 'N'
                  AND fecha_emision IS NOT NULL AND substr(fecha_emision,1,7) = ?
                  AND xml_path IS NOT NULL AND TRIM(COALESCE(xml_path,'')) != ''
                ORDER BY fecha_emision DESC LIMIT 300;
            """, (issuer_id, ym))
            months = db_rows("""
                SELECT substr(fecha_emision,1,7) AS ym, count(*) AS n
                FROM sat_cfdi
                WHERE issuer_id = ? AND direction = 'received'
                  AND UPPER(TRIM(COALESCE(tipo_comprobante,''))) = 'N'
                  AND fecha_emision IS NOT NULL
                  AND xml_path IS NOT NULL AND TRIM(COALESCE(xml_path,'')) != ''
                GROUP BY ym ORDER BY ym DESC;
            """, (issuer_id,))
            for m in months:
                m["label"] = ym_to_label(m["ym"])
            return _render_portal(
                request,
                issuer=issuer,
                template_name="portal_nomina.html",
                active_page="nomina",
                title="Nómina recibida",
                extra={
                    "rows": rows,
                    "ym": ym,
                    "ym_label": ym_to_label(ym),
                    "prev_ym": shift_ym(ym, -1),
                    "next_ym": shift_ym(ym, +1),
                    "months": months,
                },
            )
        except Exception:
            logger.exception("portal: error renderizando /portal/invoices/nomina ym=%s", ym)
            raise

    def _audit_user_issuer(request: Request):
        cookie_val = request.cookies.get(session_service.get_session_cookie_name())
        data = session_service.verify_session(cookie_val)
        user_id = data[0] if data and len(data) >= 1 else None
        issuer_id = data[1] if data and len(data) >= 2 else None
        return user_id, issuer_id

    @router.get("/sat/xml/{uuid}")
    def portal_sat_xml(request: Request, uuid: str, issuer: dict = Depends(get_portal_issuer)):
        u = (uuid or "").strip()
        if not u:
            raise HTTPException(status_code=404, detail="UUID no válido")
        conn = db()
        row = conn.execute(
            "SELECT xml_path, uuid FROM sat_cfdi WHERE issuer_id = ? AND LOWER(TRIM(uuid)) = LOWER(?) LIMIT 1",
            (issuer["id"], u),
        ).fetchone()
        conn.close()
        if not row or not row["xml_path"]:
            raise HTTPException(status_code=404, detail="XML no encontrado para este UUID")
        try:
            abs_path = _safe_abs_path(row["xml_path"])
        except ValueError:
            raise HTTPException(status_code=404, detail="Ruta XML inválida")
        if not os.path.exists(abs_path):
            raise HTTPException(status_code=404, detail="Archivo XML no existe en disco")
        uid, iid = _audit_user_issuer(request)
        if not subscription_service.can_issuer_use_sync_and_timbrado(issuer["id"], uid or 0):
            raise HTTPException(status_code=402, detail="Actualiza tu plan para descargar XML. Ve a /pricing.")
        audit.log(
            action="download_xml",
            user_id=uid,
            issuer_id=issuer["id"],
            details=u[:36],
            request=request,
            entity="cfdi",
            entity_id=u,
        )
        log_action(request, "download_xml", issuer_id=issuer["id"], entity_id=u[:36])
        with open(abs_path, "rb") as f:
            xml_bytes = f.read()
        return Response(
            content=xml_bytes,
            media_type="application/xml",
            headers={"Content-Disposition": f'inline; filename="{row["uuid"]}.xml"'},
        )

    @router.get("/sat/pdf/{uuid}")
    def portal_sat_pdf(request: Request, uuid: str, issuer: dict = Depends(get_portal_issuer), dl: int = 0):
        uuid_clean = (uuid or "").strip().split()[0] if uuid else ""
        if not uuid_clean:
            raise HTTPException(status_code=404, detail="UUID no válido")
        conn = db()
        row = conn.execute(
            "SELECT xml_path, uuid FROM sat_cfdi WHERE issuer_id = ? AND LOWER(TRIM(uuid)) = LOWER(?) LIMIT 1",
            (issuer["id"], uuid_clean),
        ).fetchone()
        conn.close()
        if not row or not row["xml_path"]:
            raise HTTPException(status_code=404, detail="XML no encontrado para este UUID")
        try:
            abs_path = _safe_abs_path(row["xml_path"])
        except ValueError:
            raise HTTPException(status_code=404, detail="Ruta XML inválida")
        if not os.path.exists(abs_path):
            raise HTTPException(status_code=404, detail="Archivo XML no existe en disco")
        uid, _ = _audit_user_issuer(request)
        if not subscription_service.can_issuer_use_sync_and_timbrado(issuer["id"], uid or 0):
            raise HTTPException(status_code=402, detail="Actualiza tu plan para descargar PDF. Ve a /pricing.")
        audit.log(
            action="download_pdf",
            user_id=uid,
            issuer_id=issuer["id"],
            details=uuid_clean[:36],
            request=request,
            entity="cfdi",
            entity_id=uuid_clean,
        )
        log_action(request, "download_pdf", issuer_id=issuer["id"], entity_id=uuid_clean[:36])
        try:
            from cfdi_pdf import parse_cfdi_xml, build_pdf
            data = parse_cfdi_xml(abs_path)
            pdf_bytes = build_pdf(data)
        except Exception as e:
            err_msg = str(e or "")
            hint = "Instala dependencias: pip install -r requirements.txt" if "reportlab" in err_msg.lower() else ""
            logger.exception("portal: error generando PDF uuid=%s", uuid_clean[:36])
            return HTMLResponse(
                "<!DOCTYPE html><html><head><meta charset=\"utf-8\"><title>Error PDF</title></head>"
                "<body id=\"pdf-error\" style=\"margin:1rem;font-family:system-ui,sans-serif;\">"
                "<p id=\"pdf-error-msg\">No se pudo generar el PDF. Intenta de nuevo más tarde.</p>"
                + (f"<p class=\"pdf-error-hint\" style=\"color:#666;\">{hint}</p>" if hint else "")
                + "</body></html>",
                status_code=500,
            )
        if not pdf_bytes:
            raise HTTPException(status_code=500, detail="La generación del PDF devolvió vacío")
        filename = f"cfdi-{uuid_clean[:8]}.pdf"
        disposition = "attachment" if dl else "inline"
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'{disposition}; filename="{filename}"',
                "Content-Length": str(len(pdf_bytes)),
            },
        )

    @router.get("/cfdi/issued/{uuid}", response_class=HTMLResponse)
    def portal_cfdi_detail_issued(request: Request, uuid: str, issuer: dict = Depends(get_portal_issuer)):
        cfdi = _get_cfdi_by_uuid(issuer["id"], uuid, "issued")
        if not cfdi:
            return _render_portal(
                request,
                issuer=issuer,
                template_name="portal_cfdi_detail.html",
                active_page="issued",
                title="CFDI no encontrado",
                extra={"cfdi": None, "direction": "issued", "error": "not_found", "requested_uuid": uuid},
                status_code=404,
            )
        uid = getattr(request.state, "user_id", None) or 0
        audit.log(
            action="cfdi_view",
            user_id=uid if uid else None,
            issuer_id=issuer["id"],
            details=f"direction=issued uuid={(uuid or '')[:36]}",
            request=request,
            entity="cfdi",
            entity_id=(uuid or "").strip()[:36],
        )
        return _render_portal(
            request,
            issuer=issuer,
            template_name="portal_cfdi_detail.html",
            active_page="issued",
            title="Detalle CFDI emitido",
            extra={"cfdi": cfdi, "direction": "issued"},
        )

    @router.get("/cfdi/received/{uuid}", response_class=HTMLResponse)
    def portal_cfdi_detail_received(request: Request, uuid: str, issuer: dict = Depends(get_portal_issuer)):
        cfdi = _get_cfdi_by_uuid(issuer["id"], uuid, "received")
        if not cfdi:
            return _render_portal(
                request,
                issuer=issuer,
                template_name="portal_cfdi_detail.html",
                active_page="received",
                title="CFDI no encontrado",
                extra={"cfdi": None, "direction": "received", "error": "not_found", "requested_uuid": uuid},
                status_code=404,
            )
        uid = getattr(request.state, "user_id", None) or 0
        audit.log(
            action="cfdi_view",
            user_id=uid if uid else None,
            issuer_id=issuer["id"],
            details=f"direction=received uuid={(uuid or '')[:36]}",
            request=request,
            entity="cfdi",
            entity_id=(uuid or "").strip()[:36],
        )
        return _render_portal(
            request,
            issuer=issuer,
            template_name="portal_cfdi_detail.html",
            active_page="received",
            title="Detalle CFDI recibido",
            extra={"cfdi": cfdi, "direction": "received"},
        )

    @router.get("/clients", response_class=HTMLResponse)
    def portal_clients(request: Request, issuer: dict = Depends(get_portal_issuer)):
        try:
            return _render_portal(
                request, issuer=issuer, template_name="portal_clients.html", active_page="clients", title="Clientes"
            )
        except Exception:
            logger.exception("portal: error renderizando /portal/clients")
            raise

    @router.get("/providers", response_class=HTMLResponse)
    def portal_providers(request: Request, issuer: dict = Depends(get_portal_issuer)):
        try:
            return _render_portal(
                request, issuer=issuer, template_name="portal_providers.html", active_page="providers", title="Proveedores"
            )
        except Exception:
            logger.exception("portal: error renderizando /portal/providers")
            raise

    @router.get("/products", response_class=HTMLResponse)
    def portal_products(request: Request, issuer: dict = Depends(get_portal_issuer)):
        try:
            return _render_portal(
                request, issuer=issuer, template_name="portal_products.html", active_page="products", title="Productos"
            )
        except Exception:
            logger.exception("portal: error renderizando /portal/products")
            raise

    @router.get("/datos-fiscales", response_class=HTMLResponse)
    def portal_datos_fiscales(request: Request, issuer: dict = Depends(get_portal_issuer)):
        """Vista read-only de datos fiscales del emisor (RFC, razón social, régimen)."""
        return _render_portal(
            request,
            issuer=issuer,
            template_name="portal_datos_fiscales.html",
            active_page="datos_fiscales",
            title="Datos fiscales",
            extra={
                "issuer_razon_social": issuer.get("alias") or issuer.get("rfc") or "—",
            },
        )

    @router.get("/summary", response_class=HTMLResponse)
    def portal_summary(request: Request, issuer: dict = Depends(get_portal_issuer), ym: str = None):
        try:
            issuer_id = issuer["id"]
            if not ym:
                ym = ym_now()
            tot_issued = _get_month_totals(issuer_id, ym, "issued")
            tot_received = _get_month_totals(issuer_id, ym, "received")
            ingresos_sin_iva = tot_issued["total_base"]
            gastos_sin_iva = tot_received["total_base"]
            iva_retenciones = tot_issued["total_retenciones"]
            iva_recibido_neto = tot_issued["total_iva_neto"]
            iva_pagado = tot_received["total_iva"]
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
            return _render_portal(
                request,
                issuer=issuer,
                template_name="portal_summary.html",
                active_page="summary",
                title="Resumen",
                extra={
                    "ym": ym,
                    "ym_label": ym_to_label(ym),
                    "prev_ym": shift_ym(ym, -1),
                    "next_ym": shift_ym(ym, +1),
                    "months": months,
                    "ingresos_sin_iva": ingresos_sin_iva,
                    "gastos_sin_iva": gastos_sin_iva,
                    "iva_recibido_neto": iva_recibido_neto,
                    "iva_retenciones": iva_retenciones,
                    "iva_pagado": iva_pagado,
                },
            )
        except Exception:
            logger.exception("portal: error renderizando /portal/summary ym=%s", ym)
            raise

    @router.get("/plan", response_class=HTMLResponse)
    def portal_plan(request: Request, issuer: dict = Depends(get_portal_issuer), success: str = Query(""), canceled: str = Query("")):
        user_id = getattr(request.state, "user_id", None) or 0
        subscription = subscription_service.get_subscription_by_user_id(user_id) if user_id else None
        is_active = subscription_service.is_subscription_active(user_id)
        return _render_portal(
            request,
            issuer=issuer,
            template_name="portal_plan.html",
            active_page="plan",
            title="Mi plan",
            extra={
                "subscription": subscription,
                "is_active": is_active,
                "success": success == "1",
                "canceled": canceled == "1",
            },
        )

    @router.get("/info", response_class=RedirectResponse)
    def portal_info():
        """Redirige a la página pública de seguridad (misma para usuarios y visitantes)."""
        return RedirectResponse(url="/seguridad", status_code=302)

    # ---------- SAT sync (encolar desde UI; el worker procesa) ----------
    @router.post("/sat/sync", response_class=JSONResponse)
    def portal_sat_sync(request: Request, issuer: dict = Depends(get_portal_issuer)):
        """Encola sincronización SAT (issued + received). Requiere FIEL configurada y validada."""
        if rate_limit_service.is_rate_limited(request, "sat_sync"):
            return JSONResponse({"ok": False, "message": "Demasiados intentos. Espera un minuto."}, status_code=429)
        issuer_id = issuer["id"]
        user_id = getattr(request.state, "user_id", 0) or 0
        if not subscription_service.can_issuer_use_sync_and_timbrado(issuer_id, user_id):
            return JSONResponse(
                {"ok": False, "message": "Tu periodo de prueba ha terminado. Actualiza tu plan para seguir sincronizando."},
                status_code=402,
            )
        conn = db()
        try:
            _ensure_sat_credentials_validation_columns(conn)
            cred = conn.execute(
                "SELECT validation_ok FROM sat_credentials WHERE issuer_id = ?",
                (issuer_id,),
            ).fetchone()
            if not cred:
                return JSONResponse({"ok": False, "message": "Configura y valida tu FIEL en Ajustes primero."}, status_code=400)
            if cred["validation_ok"] != 1:
                return JSONResponse({"ok": False, "message": "Valida tu FIEL en Ajustes antes de sincronizar."}, status_code=400)
            # No encolar si ya hay jobs en cola o en ejecución para este issuer
            pending = conn.execute(
                "SELECT 1 FROM sat_jobs WHERE issuer_id = ? AND status IN ('queued','running') LIMIT 1",
                (issuer_id,),
            ).fetchone()
            if pending:
                return JSONResponse({"ok": False, "message": "Ya hay una sincronización en curso. Espera a que termine."}, status_code=409)
            conn.execute(
                """
                INSERT INTO sat_jobs (issuer_id, job_type, direction, status, created_at, updated_at)
                VALUES (?, 'xml', 'issued', 'queued', datetime('now'), datetime('now')),
                       (?, 'xml', 'received', 'queued', datetime('now'), datetime('now'))
                """,
                (issuer_id, issuer_id),
            )
            conn.commit()
        finally:
            conn.close()
        return JSONResponse({"ok": True, "message": "Sincronización iniciada."})

    @router.get("/sat/status", response_class=JSONResponse)
    def portal_sat_status(request: Request, issuer: dict = Depends(get_portal_issuer)):
        """Estado del sync SAT para este issuer: último sync, en proceso / ok / error."""
        issuer_id = issuer["id"]
        conn = db()
        try:
            running = conn.execute(
                "SELECT 1 FROM sat_jobs WHERE issuer_id = ? AND status IN ('queued','running') LIMIT 1",
                (issuer_id,),
            ).fetchone()
            last_ok = conn.execute(
                "SELECT MAX(finished_at) AS t FROM sat_jobs WHERE issuer_id = ? AND status = 'ok'",
                (issuer_id,),
            ).fetchone()
            last_error = conn.execute(
                "SELECT finished_at, last_error FROM sat_jobs WHERE issuer_id = ? AND status = 'error' ORDER BY finished_at DESC LIMIT 1",
                (issuer_id,),
            ).fetchone()
            sync_state = conn.execute(
                "SELECT MAX(last_run_at) AS t FROM sat_sync_state WHERE issuer_id = ?",
                (issuer_id,),
            ).fetchone()
        finally:
            conn.close()
        last_sync_at = (sync_state and sync_state["t"]) or (last_ok and last_ok["t"]) or None
        if running:
            status = "running"
            message = "Sincronización en proceso"
        elif last_error and last_ok and last_error["t"] and last_ok["t"] and last_error["t"] > last_ok["t"]:
            status = "error"
            message = (last_error["last_error"] or "Error en la última sincronización")[:200]
        elif last_error and not last_ok:
            status = "error"
            message = (last_error["last_error"] or "Error en la última sincronización")[:200]
        else:
            status = "ok"
            message = None
        return JSONResponse({
            "ok": True,
            "last_sync_at": last_sync_at,
            "status": status,
            "message": message,
        })

    # ---------- Catálogo sugerido desde CFDI emitidos (auto-captura) ----------
    @router.post("/catalog/backfill", response_class=JSONResponse)
    def portal_catalog_backfill(
        request: Request,
        payload: dict = Body(default_factory=dict),
        issuer: dict = Depends(get_portal_issuer),
    ):
        """
        Dispara backfill de catálogo sugerido (clients + product_observations) desde CFDI emitidos ya guardados.
        Responde JSON con métricas. Multi-issuer: siempre filtra por issuer_id actual.
        """
        if rate_limit_service.is_rate_limited(request, "catalog_backfill"):
            return JSONResponse({"ok": False, "detail": "Demasiados intentos. Espera un minuto."}, status_code=429)
        issuer_id = int(issuer.get("id") or 0)
        if issuer_id <= 0:
            raise HTTPException(status_code=401, detail="Sesión inválida")

        limit = payload.get("limit") if isinstance(payload, dict) else None
        since = payload.get("since") if isinstance(payload, dict) else None
        try:
            result = backfill_catalog_from_existing_cfdi(
                issuer_id,
                limit=int(limit) if limit is not None and str(limit).strip() else None,
                since=str(since).strip() if since is not None and str(since).strip() else None,
            )
        except Exception as e:
            logger.exception("portal catalog backfill: issuer=%s", issuer_id)
            raise HTTPException(status_code=500, detail="No se pudo ejecutar el backfill. Revisa que existan XML emitidos y que las migraciones estén aplicadas.")

        return JSONResponse(
            {
                "ok": True,
                "processed": result.processed,
                "clients_upserted": result.clients_upserted,
                "observations_upserted": result.observations_upserted,
                "errors_count": result.errors_count,
                "errors_sample": (result.errors or [])[:10],
            }
        )

    # ---------- Bank: PDF → Excel (estado de cuenta) ----------
    MAX_BANK_PDF_SIZE = 15 * 1024 * 1024  # 15MB

    def _ensure_bank_exports_table(conn) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS bank_pdf_exports (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              issuer_id INTEGER NOT NULL,
              file_id TEXT NOT NULL,
              pdf_path TEXT NOT NULL,
              xlsx_path TEXT NOT NULL,
              meta_json TEXT,
              created_at TEXT NOT NULL DEFAULT (datetime('now')),
              UNIQUE(issuer_id, file_id)
            );
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_bank_pdf_exports_issuer ON bank_pdf_exports(issuer_id, created_at);")

    @router.get("/bank/pdf-to-excel", response_class=HTMLResponse)
    def portal_bank_pdf_to_excel(request: Request, issuer: dict = Depends(get_portal_issuer)):
        return _render_portal(
            request,
            issuer=issuer,
            template_name="portal_bank_pdf_to_excel.html",
            active_page="bank_pdf_to_excel",
            title="Convertir Edo. de Cuenta",
        )

    @router.post("/bank/pdf-to-excel/upload", response_class=JSONResponse)
    async def portal_bank_pdf_to_excel_upload(
        request: Request,
        issuer: dict = Depends(get_portal_issuer),
        file: UploadFile = File(...),
    ):
        issuer_id = int(issuer.get("id") or 0)
        if issuer_id <= 0:
            raise HTTPException(status_code=401, detail="Sesión inválida")

        # Validaciones básicas
        filename = (file.filename or "").strip()
        name_l = filename.lower()
        if not name_l.endswith(".pdf"):
            raise HTTPException(status_code=400, detail="El archivo debe ser .pdf")
        content_type = (file.content_type or "").lower().strip()
        if content_type and content_type not in ("application/pdf", "application/x-pdf"):
            raise HTTPException(status_code=400, detail="El archivo debe ser un PDF válido (MIME application/pdf)")

        storage_root = get_storage_root(BASE_DIR)
        uploads_rel_dir = os.path.join("uploads", str(issuer_id), "bank_statements")
        exports_rel_dir = os.path.join("exports", str(issuer_id), "bank_statements")

        # Guardar PDF con nombre único (timestamp + hash)
        sha = hashlib.sha256()
        size = 0
        chunks: list[bytes] = []
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_BANK_PDF_SIZE:
                raise HTTPException(status_code=400, detail="El PDF excede el máximo de 15MB.")
            sha.update(chunk)
            chunks.append(chunk)
        if size <= 0:
            raise HTTPException(status_code=400, detail="El PDF está vacío.")

        digest = sha.hexdigest()
        stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        pdf_name = f"{stamp}_{digest[:12]}.pdf"
        pdf_rel_path = os.path.join(uploads_rel_dir, pdf_name)
        pdf_abs_path = safe_join(storage_root, pdf_rel_path)
        ensure_parent_dir(pdf_abs_path)
        with open(pdf_abs_path, "wb") as f:
            for ch in chunks:
                f.write(ch)

        file_id = secrets.token_urlsafe(16)
        xlsx_name = f"{stamp}_{file_id[:10]}.xlsx"
        xlsx_rel_path = os.path.join(exports_rel_dir, xlsx_name)
        xlsx_abs_path = safe_join(storage_root, xlsx_rel_path)

        try:
            meta = convert_pdf_to_xlsx(pdf_abs_path, xlsx_abs_path)
        except Exception as e:
            logger.exception("bank pdf-to-excel: error convirtiendo issuer=%s pdf=%s", issuer_id, pdf_rel_path)
            raise HTTPException(status_code=500, detail="No se pudo convertir el PDF. Intenta con otro archivo o revisa que el PDF tenga texto.")

        conn = db()
        try:
            _ensure_bank_exports_table(conn)
            conn.execute(
                """
                INSERT INTO bank_pdf_exports (issuer_id, file_id, pdf_path, xlsx_path, meta_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (issuer_id, file_id, pdf_rel_path, xlsx_rel_path, json.dumps(meta, ensure_ascii=False)[:4000]),
            )
            conn.commit()
        finally:
            conn.close()

        log_action(request, "bank_pdf_to_excel", issuer_id=issuer_id, entity_id=file_id[:32])
        return JSONResponse(
            {
                "ok": True,
                "file_id": file_id,
                "meta": meta,
                "download_url": f"/portal/bank/pdf-to-excel/download/{file_id}",
            }
        )

    @router.get("/bank/pdf-to-excel/download/{file_id}")
    def portal_bank_pdf_to_excel_download(
        request: Request,
        file_id: str,
        issuer: dict = Depends(get_portal_issuer),
    ):
        issuer_id = int(issuer.get("id") or 0)
        fid = (file_id or "").strip()
        if issuer_id <= 0:
            raise HTTPException(status_code=401, detail="Sesión inválida")
        if not fid:
            raise HTTPException(status_code=404, detail="Archivo no encontrado")

        conn = db()
        try:
            _ensure_bank_exports_table(conn)
            row = conn.execute(
                "SELECT xlsx_path FROM bank_pdf_exports WHERE issuer_id = ? AND file_id = ? LIMIT 1",
                (issuer_id, fid),
            ).fetchone()
        finally:
            conn.close()
        if not row:
            raise HTTPException(status_code=404, detail="Archivo no encontrado")

        storage_root = get_storage_root(BASE_DIR)
        xlsx_rel_path = (row["xlsx_path"] or "").strip()
        if not xlsx_rel_path:
            raise HTTPException(status_code=404, detail="Archivo no encontrado")
        try:
            xlsx_abs_path = safe_join(storage_root, xlsx_rel_path)
        except ValueError:
            raise HTTPException(status_code=404, detail="Ruta inválida")
        if not os.path.exists(xlsx_abs_path):
            raise HTTPException(status_code=404, detail="El archivo ya no existe en disco")

        filename = f"estado_cuenta_{fid[:8]}.xlsx"
        return FileResponse(
            path=xlsx_abs_path,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            filename=filename,
        )

    # ---------- SAT credentials (FIEL) upload & validate ----------
    MAX_FIEL_SIZE = 2 * 1024 * 1024  # 2 MB
    ALLOWED_CER = (".cer",)
    ALLOWED_KEY = (".key",)

    @router.get("/config/sat", response_class=HTMLResponse)
    def portal_config_sat(request: Request, issuer: dict = Depends(get_portal_issuer)):
        issuer_id = issuer["id"]
        conn = db()
        try:
            _ensure_sat_credentials_validation_columns(conn)
            row = conn.execute(
                "SELECT fiel_cer_path, fiel_key_path, validation_at, validation_ok, validation_message FROM sat_credentials WHERE issuer_id = ?",
                (issuer_id,),
            ).fetchone()
        finally:
            conn.close()
        cred = dict(row) if row else None
        return _render_portal(
            request,
            issuer=issuer,
            template_name="portal_config_sat.html",
            active_page="config_sat",
            title="FIEL / Credenciales SAT",
            extra={
                "sat_cred": cred,
                "has_fiel": cred is not None,
                "validation_at": cred.get("validation_at") if cred else None,
                "validation_ok": cred.get("validation_ok") if cred else None,
                "validation_message": cred.get("validation_message") if cred else None,
            },
        )

    @router.post("/config/sat")
    async def portal_config_sat_save(
        request: Request,
        issuer: dict = Depends(get_portal_issuer),
        fiel_cer: UploadFile = File(...),
        fiel_key: UploadFile = File(...),
        fiel_password: str = Form(""),
        csrf_token: str | None = Form(None),
    ):
        token_val = (csrf_token or request.headers.get("X-CSRF-Token") or "").strip()
        if not csrf_service.verify_csrf_token(token_val):
            raise HTTPException(status_code=403, detail="Token CSRF inválido o expirado")
        if rate_limit_service.is_rate_limited(request, "upload"):
            raise HTTPException(status_code=429, detail="Demasiados intentos. Espera un minuto.")
        issuer_id = issuer["id"]
        # Validar extensiones
        cer_name = (fiel_cer.filename or "").lower()
        key_name = (fiel_key.filename or "").lower()
        if not any(cer_name.endswith(e) for e in ALLOWED_CER):
            raise HTTPException(status_code=400, detail="El archivo del certificado debe ser .cer")
        if not any(key_name.endswith(e) for e in ALLOWED_KEY):
            raise HTTPException(status_code=400, detail="El archivo de la clave debe ser .key")
        if not (fiel_password and fiel_password.strip()):
            raise HTTPException(status_code=400, detail="La contraseña FIEL es obligatoria")
        cer_body = await fiel_cer.read()
        key_body = await fiel_key.read()
        if len(cer_body) > MAX_FIEL_SIZE or len(key_body) > MAX_FIEL_SIZE:
            raise HTTPException(status_code=400, detail="Cada archivo debe medir como máximo 2 MB")
        cred_dir = _credentials_dir(issuer_id)
        cer_path = os.path.join(cred_dir, "fiel.cer")
        key_path = os.path.join(cred_dir, "fiel.key")
        rel_cer = f"storage/credentials/{issuer_id}/fiel.cer"
        rel_key = f"storage/credentials/{issuer_id}/fiel.key"
        with open(cer_path, "wb") as f:
            f.write(cer_body)
        with open(key_path, "wb") as f:
            f.write(key_body)
        # Permisos 0600: solo el propietario puede leer/escribir (sin prometer cifrado)
        os.chmod(cer_path, 0o600)
        os.chmod(key_path, 0o600)
        password = fiel_password.strip()
        conn = db()
        try:
            _ensure_sat_credentials_validation_columns(conn)
            conn.execute(
                """
                INSERT INTO sat_credentials (issuer_id, fiel_cer_path, fiel_key_path, fiel_key_password, updated_at)
                VALUES (?, ?, ?, ?, datetime('now'))
                ON CONFLICT(issuer_id) DO UPDATE SET
                    fiel_cer_path = excluded.fiel_cer_path,
                    fiel_key_path = excluded.fiel_key_path,
                    fiel_key_password = excluded.fiel_key_password,
                    updated_at = datetime('now')
                """,
                (issuer_id, rel_cer, rel_key, password),
            )
            conn.commit()
        finally:
            conn.close()
        uid = getattr(request.state, "user_id", None) or 0
        audit.log(action="credentials_uploaded", user_id=uid, issuer_id=issuer_id, request=request, entity="sat_credentials", entity_id=str(issuer_id))
        log_action(request, "credentials_uploaded", issuer_id=issuer_id)
        # Validación post-upload: ejecutar check_fiel y persistir estado para mostrar en UI
        valid_ok, valid_message = _run_fiel_validation(issuer_id)
        audit.log(action="credentials_validated", user_id=uid, issuer_id=issuer_id, request=request, entity="sat_credentials", entity_id=str(issuer_id), details=f"ok={valid_ok}")
        log_action(request, "credentials_validated", issuer_id=issuer_id)
        if request.headers.get("accept", "").find("application/json") >= 0:
            return JSONResponse({"ok": True, "message": "Credenciales guardadas.", "validation_ok": valid_ok, "validation_message": valid_message})
        return RedirectResponse(url="/portal/config/sat?saved=1", status_code=302)

    @router.post("/config/sat/validate", response_class=JSONResponse)
    def portal_config_sat_validate(request: Request, issuer: dict = Depends(get_portal_issuer)):
        if rate_limit_service.is_rate_limited(request, "validate"):
            return JSONResponse({"ok": False, "message": "Demasiados intentos. Espera un minuto."}, status_code=429)
        issuer_id = issuer["id"]
        ok, message = _run_fiel_validation(issuer_id)
        if not message:
            message = "FIEL válida." if ok else "Error al validar la FIEL."
        uid = getattr(request.state, "user_id", None) or 0
        audit.log(action="credentials_validated", user_id=uid, issuer_id=issuer_id, request=request, entity="sat_credentials", entity_id=str(issuer_id), details=f"ok={ok}")
        log_action(request, "credentials_validated", issuer_id=issuer_id)
        return JSONResponse({"ok": ok, "message": message})

    return router
