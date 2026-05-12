"""Portal month_close routes."""
import logging
import os

from fastapi import Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response

from database import db_rows
from routers.deps import get_portal_issuer
from routers.portal._helpers import (
    render_portal,
    ym_now,
)
from services import audit, file_access_log
from services.action_log import log_action
from services.auth import csrf as csrf_service
from services.auth import rate_limit as rate_limit_service
from services.sat.sat_sync import get_month_totals, get_sat_sync_status
from services.ym_helpers import is_annual, sanitize_ym, ym_sql_filter, ym_to_label

logger = logging.getLogger(__name__)

_get_month_totals = get_month_totals
_get_sat_sync_status = get_sat_sync_status


def register_month_close_routes(router, templates):
    """Register Month Close routes on the portal router."""

    def _render_portal(request, **kwargs):
        return render_portal(templates, request, **kwargs)

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

    @router.get("/summary", response_class=RedirectResponse)
    def portal_summary_redirect(ym: str | None = Query(None)):
        """Redirect legacy /summary to /home (summary folded into home)."""
        url = f"/portal/home?ym={ym}" if ym else "/portal/home"
        return RedirectResponse(url=url, status_code=302)

    # ---------- Month Close (cierre mensual PF) ----------
    @router.get("/month-close", response_class=HTMLResponse)
    def portal_month_close(request: Request, issuer: dict = Depends(get_portal_issuer), ym: str | None = Query(None)):
        issuer_id = int(issuer.get("id") or 0)
        if issuer_id <= 0:
            raise HTTPException(status_code=401, detail="Sesión inválida")
        ym_val = sanitize_ym(ym or "", ym_now())
        # Month-close is inherently monthly — redirect annual to current month
        if is_annual(ym_val):
            return RedirectResponse(url=f"/portal/month-close?ym={ym_now()}", status_code=302)
        from services import month_close as month_close_service

        status = month_close_service.get_status(issuer_id, ym_val)
        ov = status.get("overrides") if isinstance(status.get("overrides"), dict) else {}

        _ym_filt = ym_sql_filter(ym_val)
        issued_count = db_rows(
            f"""
            SELECT COUNT(*) AS n FROM sat_cfdi
            WHERE issuer_id = ? AND direction = 'issued' AND fecha_emision IS NOT NULL
              AND {_ym_filt} AND (total IS NULL OR total >= 0.01)
            """,
            (issuer_id, ym_val),
        )
        received_count = db_rows(
            f"""
            SELECT COUNT(*) AS n FROM sat_cfdi
            WHERE issuer_id = ? AND direction = 'received' AND fecha_emision IS NOT NULL
              AND {_ym_filt} AND total IS NOT NULL AND total >= 0.01
              AND (tipo_comprobante IS NULL OR UPPER(TRIM(tipo_comprobante)) != 'N')
            """,
            (issuer_id, ym_val),
        )
        n_issued = int(issued_count[0]["n"] if issued_count else 0)
        n_received = int(received_count[0]["n"] if received_count else 0)

        movements_count = 0
        try:
            r = db_rows("SELECT COUNT(*) AS n FROM bank_movements WHERE issuer_id = ? AND period_month = ?", (issuer_id, ym_val))
            movements_count = int(r[0]["n"] if r else 0)
        except Exception:
            movements_count = 0

        tot_issued = _get_month_totals(issuer_id, ym_val, "issued")
        tot_received = _get_month_totals(issuer_id, ym_val, "received")
        iva_est = {
            "iva_recibido_neto": float(tot_issued.get("total_iva_neto") or 0),
            "iva_pagado": float(tot_received.get("total_iva") or 0),
            "iva_estimado_a_pagar": round(float(tot_issued.get("total_iva_neto") or 0) - float(tot_received.get("total_iva") or 0), 2),
        }

        has_acuse = month_close_service.pdf_exists(issuer_id=issuer_id, ym=ym_val, kind="acuse")
        has_opinion = month_close_service.pdf_exists(issuer_id=issuer_id, ym=ym_val, kind="opinion")

        items = [
            {"key": "sync_issued", "label": "Facturas emitidas sincronizadas", "ok": bool(n_issued > 0), "meta": f"{n_issued} este mes"},
            {"key": "sync_received", "label": "Facturas recibidas sincronizadas", "ok": bool(n_received > 0), "meta": f"{n_received} este mes"},
            {"key": "bank_movements", "label": "Movimientos bancarios cargados", "ok": bool(movements_count > 0), "meta": f"{movements_count} este mes"},
            {"key": "reconciliation", "label": "Conciliación: gastos sin factura / facturas sin movimiento", "ok": False, "meta": "MVP: en progreso"},
            {"key": "tax_estimate", "label": "Estimación de impuestos (IVA)", "ok": bool(n_issued > 0 or n_received > 0), "meta": f"IVA est.: {iva_est['iva_estimado_a_pagar']:.2f}"},
            {"key": "acuse", "label": "Subir acuse de declaración (PDF)", "ok": bool(has_acuse), "meta": "PDF"},
            {"key": "opinion", "label": "Subir opinión de cumplimiento (PDF)", "ok": bool(has_opinion), "meta": "PDF"},
        ]
        for it in items:
            if it["key"] in ov:
                it["ok"] = bool(ov[it["key"]])

        return _render_portal(
            request,
            issuer=issuer,
            template_name="portal_month_close.html",
            active_page="month_close",
            title="Cierre del mes",
            extra={
                "ym": ym_val,
                "ym_label": ym_to_label(ym_val),
                "items": items,
                "status": status,
                "iva_est": iva_est,
                "csrf_token": csrf_service.generate_csrf_token(),
                "has_acuse": has_acuse,
                "has_opinion": has_opinion,
                "month_status": month_close_service.get_month_status_enum(issuer_id, ym_val),
            },
        )

    @router.post("/month-close/status", response_class=RedirectResponse)
    def portal_month_close_status(
        request: Request,
        issuer: dict = Depends(get_portal_issuer),
        ym: str = Form(...),
        status: str = Form(...),
        csrf_token: str | None = Form(None),
    ):
        token_val = (csrf_token or request.headers.get("X-CSRF-Token") or "").strip()
        if not csrf_service.verify_csrf_token(token_val):
            raise HTTPException(status_code=403, detail="Token CSRF inválido o expirado")
        issuer_id = int(issuer.get("id") or 0)
        from services import month_close as month_close_service

        try:
            month_close_service.save_month_close(issuer_id, ym, status=status)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        log_action(request, "month_close_status_change", issuer_id=issuer_id, ym=ym, status=status)
        return RedirectResponse(url=f"/portal/month-close?ym={ym}", status_code=302)

    @router.post("/month-close/override", response_class=RedirectResponse)
    def portal_month_close_override(
        request: Request,
        issuer: dict = Depends(get_portal_issuer),
        ym: str = Form(...),
        key: str = Form(...),
        value: str = Form("0"),
        csrf_token: str | None = Form(None),
    ):
        token_val = (csrf_token or request.headers.get("X-CSRF-Token") or "").strip()
        if not csrf_service.verify_csrf_token(token_val):
            raise HTTPException(status_code=403, detail="Token CSRF inválido o expirado")
        issuer_id = int(issuer.get("id") or 0)
        from services import month_close as month_close_service

        month_close_service.set_override(issuer_id, ym, key, value in ("1", "true", "on", "yes"))
        return RedirectResponse(url=f"/portal/month-close?ym={ym}", status_code=302)

    @router.post("/month-close/upload", response_class=RedirectResponse)
    async def portal_month_close_upload(
        request: Request,
        issuer: dict = Depends(get_portal_issuer),
        ym: str = Form(...),
        kind: str = Form(...),
        pdf: UploadFile = File(...),
        csrf_token: str | None = Form(None),
    ):
        token_val = (csrf_token or request.headers.get("X-CSRF-Token") or "").strip()
        if not csrf_service.verify_csrf_token(token_val):
            raise HTTPException(status_code=403, detail="Token CSRF inválido o expirado")
        if rate_limit_service.is_rate_limited(request, "month_close_upload"):
            raise HTTPException(status_code=429, detail="Demasiados intentos. Espera un minuto.")
        issuer_id = int(issuer.get("id") or 0)
        kind_norm = (kind or "").strip().lower()
        if kind_norm not in ("acuse", "opinion"):
            raise HTTPException(status_code=400, detail="Tipo inválido")
        pdf_name = (pdf.filename or "").strip().lower()
        if pdf_name and not pdf_name.endswith(".pdf"):
            raise HTTPException(status_code=400, detail="El archivo debe ser .pdf")
        body = await pdf.read()
        if not body or len(body) < 10:
            raise HTTPException(status_code=400, detail="Archivo vacío")
        if len(body) > 10 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="PDF demasiado grande (máx 10 MB)")
        if not body.startswith(b"%PDF"):
            raise HTTPException(status_code=400, detail="El archivo debe ser PDF")
        from services import month_close as month_close_service

        rel = month_close_service.write_pdf_to_storage(issuer_id=issuer_id, ym=ym, kind=kind_norm, pdf_bytes=body)
        audit.log(action="month_close_upload", user_id=getattr(request.state, "user_id", 0) or 0, issuer_id=issuer_id, request=request, entity="month_close", entity_id=f"{ym}:{kind_norm}")
        log_action(request, "month_close_upload", issuer_id=issuer_id, ym=ym, kind=kind_norm)
        file_access_log.log_file_access(
            request=request,
            action="upload_month_close_pdf",
            issuer_id=issuer_id,
            user_id=getattr(request.state, "user_id", None),
            file_path=rel,
            entity="month_close",
            entity_id=f"{ym}:{kind_norm}",
        )
        return RedirectResponse(url=f"/portal/month-close?ym={ym}", status_code=302)

    @router.get("/month-close/download/{ym}/{kind}", response_class=Response)
    def portal_month_close_download(
        request: Request,
        issuer: dict = Depends(get_portal_issuer),
        ym: str = "",
        kind: str = "",
        dl: int = 0,
    ):
        issuer_id = int(issuer.get("id") or 0)
        from services import month_close as month_close_service

        try:
            abs_path, rel = month_close_service.get_pdf_abs_path(issuer_id=issuer_id, ym=ym, kind=kind)
        except ValueError:
            raise HTTPException(status_code=404, detail="Archivo no encontrado")
        if not os.path.exists(abs_path):
            raise HTTPException(status_code=404, detail="Archivo no encontrado")
        disposition = "attachment" if int(dl or 0) == 1 else "inline"
        file_access_log.log_file_access(
            request=request,
            action="download_month_close_pdf",
            issuer_id=issuer_id,
            user_id=getattr(request.state, "user_id", None),
            file_path=rel,
            entity="month_close",
            entity_id=f"{ym}:{kind}",
        )
        filename = f"{kind}_{ym}.pdf"
        return FileResponse(path=abs_path, media_type="application/pdf", filename=filename, headers={"Content-Disposition": f"{disposition}; filename=\"{filename}\""})

