"""Constancia de Situación Fiscal — upload and diff routes."""
import logging

from fastapi import Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse

from routers.deps import get_portal_issuer
from routers.portal._helpers import render_portal
from services.action_log import log_action
from services.auth import csrf as csrf_service

logger = logging.getLogger(__name__)

MAX_PDF_SIZE = 5 * 1024 * 1024  # 5 MB


def register_constancia_routes(router, templates):
    """Register /portal/settings/constancia/* routes."""

    @router.post("/settings/constancia/upload", response_class=HTMLResponse)
    async def upload_constancia(
        request: Request,
        issuer: dict = Depends(get_portal_issuer),
        csrf_token: str = Form(""),
        pdf_file: UploadFile = File(...),
    ):
        """Upload constancia PDF, parse it, and show diff."""
        if not csrf_service.verify_csrf_token(csrf_token):
            raise HTTPException(status_code=403, detail="Token CSRF inválido")

        role = getattr(request.state, "membership_role", "viewer")
        if role not in ("owner", "admin"):
            raise HTTPException(status_code=403, detail="Solo owner/admin puede subir constancia")

        issuer_id = int(issuer.get("id") or 0)
        if issuer_id <= 0:
            raise HTTPException(status_code=401, detail="Sesión inválida")

        # Validate file
        if not pdf_file.filename or not pdf_file.filename.lower().endswith(".pdf"):
            return render_portal(
                templates, request, issuer=issuer,
                template_name="portal_constancia_result.html",
                active_page="settings", title="Constancia",
                result={"ok": False, "error": "Solo se aceptan archivos PDF"},
            )

        pdf_bytes = await pdf_file.read()
        if len(pdf_bytes) > MAX_PDF_SIZE:
            return render_portal(
                templates, request, issuer=issuer,
                template_name="portal_constancia_result.html",
                active_page="settings", title="Constancia",
                result={"ok": False, "error": "El archivo es demasiado grande (máx. 5 MB)"},
            )
        if len(pdf_bytes) < 100:
            return render_portal(
                templates, request, issuer=issuer,
                template_name="portal_constancia_result.html",
                active_page="settings", title="Constancia",
                result={"ok": False, "error": "El archivo está vacío o dañado"},
            )

        from services.constancia.service import process_constancia_upload

        result = process_constancia_upload(
            issuer_id=issuer_id,
            pdf_bytes=pdf_bytes,
            filename=pdf_file.filename,
        )

        log_action(request, "constancia_uploaded", issuer_id=issuer_id)

        return render_portal(
            templates, request, issuer=issuer,
            template_name="portal_constancia_result.html",
            active_page="settings", title="Constancia — Resultado",
            result=result,
        )

    @router.post("/settings/constancia/apply", response_class=RedirectResponse)
    async def apply_constancia(
        request: Request,
        issuer: dict = Depends(get_portal_issuer),
        csrf_token: str = Form(""),
    ):
        """Apply extracted constancia data to the issuer profile."""
        if not csrf_service.verify_csrf_token(csrf_token):
            raise HTTPException(status_code=403, detail="Token CSRF inválido")

        role = getattr(request.state, "membership_role", "viewer")
        if role not in ("owner", "admin"):
            raise HTTPException(status_code=403, detail="Solo owner/admin")

        issuer_id = int(issuer.get("id") or 0)
        from services.constancia.service import apply_extracted_data

        result = apply_extracted_data(issuer_id)
        log_action(request, "constancia_applied", issuer_id=issuer_id)

        if result.get("ok"):
            return RedirectResponse(
                url="/portal/settings?success=Datos+fiscales+actualizados+desde+constancia",
                status_code=302,
            )
        return RedirectResponse(
            url="/portal/settings?error=" + (result.get("error", "Error").replace(" ", "+")),
            status_code=302,
        )
