"""Portal declaration routes — upload, review, list for accountants and users."""
import json
import logging

from fastapi import Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse

from routers.deps import get_portal_issuer
from routers.portal._helpers import render_portal
from services.declarations.service import (
    get_declaration_by_id,
    get_declarations_for_issuer,
    get_declarations_uploaded_by,
    process_uploaded_pdf,
    validate_declaration,
)

logger = logging.getLogger(__name__)

MAX_UPLOAD_SIZE = 10 * 1024 * 1024  # 10 MB


def register_declarations_routes(router, templates):
    """Register declaration routes on the portal router."""

    def _render_portal(request, **kwargs):
        return render_portal(templates, request, **kwargs)

    # ── Accountant routes ──

    @router.get("/contador/declaraciones", response_class=HTMLResponse)
    def portal_contador_declaraciones(
        request: Request,
        issuer: dict = Depends(get_portal_issuer),
    ):
        user_id = getattr(request.state, "user_id", 0)
        declarations = get_declarations_uploaded_by(user_id)
        return _render_portal(
            request, issuer=issuer,
            template_name="contador_declaraciones.html",
            active_page="declaraciones",
            title="Declaraciones",
            extra={"declarations": declarations},
        )

    @router.post("/contador/declaraciones/upload")
    async def portal_contador_upload(
        request: Request,
        files: list[UploadFile] = File(...),
        target_issuer_id: int = Form(None),
        issuer: dict = Depends(get_portal_issuer),
    ):
        user_id = getattr(request.state, "user_id", 0)
        results = []
        for f in files:
            if not f.filename or not f.filename.lower().endswith(".pdf"):
                results.append({"filename": f.filename, "status": "rejected",
                                "reason": "Not a PDF"})
                continue
            pdf_bytes = await f.read()
            if len(pdf_bytes) > MAX_UPLOAD_SIZE:
                results.append({"filename": f.filename, "status": "rejected",
                                "reason": "File too large (max 10 MB)"})
                continue
            try:
                result = process_uploaded_pdf(
                    pdf_bytes=pdf_bytes,
                    uploaded_by_user_id=user_id,
                    filename=f.filename,
                    target_issuer_id=target_issuer_id or None,
                )
                result["filename"] = f.filename
                results.append(result)
            except Exception as exc:
                logger.exception("Declaration upload error: %s", f.filename)
                results.append({"filename": f.filename, "status": "error",
                                "reason": str(exc)})
        return JSONResponse({"ok": True, "results": results})

    @router.get("/contador/declaraciones/{declaration_id}/review", response_class=HTMLResponse)
    def portal_contador_review(
        request: Request,
        declaration_id: int,
        issuer: dict = Depends(get_portal_issuer),
    ):
        decl = get_declaration_by_id(declaration_id, issuer["id"])
        if not decl:
            return _render_portal(
                request, issuer=issuer,
                template_name="components/portal_error_inline.html",
                active_page="declaraciones",
                title="No encontrada",
                error="Declaracion no encontrada",
                status_code=404,
            )
        raw_json = {}
        if decl.get("raw_extracted_json"):
            try:
                raw_json = json.loads(decl["raw_extracted_json"])
            except Exception:
                pass
        return _render_portal(
            request, issuer=issuer,
            template_name="contador_declaraciones_review.html",
            active_page="declaraciones",
            title=f"Revisar declaracion — {decl.get('tipo', '')}",
            extra={"decl": decl, "raw_json": raw_json},
        )

    @router.post("/contador/declaraciones/{declaration_id}/validate")
    def portal_contador_validate(
        request: Request,
        declaration_id: int,
        issuer: dict = Depends(get_portal_issuer),
    ):
        decl = get_declaration_by_id(declaration_id, issuer["id"])
        if not decl:
            return JSONResponse({"ok": False, "error": "Not found"}, status_code=404)
        # Simple validation — mark as validated
        validate_declaration(declaration_id, issuer["id"], {})

        # Enqueue email notification to the user
        _notify_user_of_declaration(decl, issuer)

        return JSONResponse({"ok": True, "status": "validated"})

    # ── User routes ──

    @router.get("/declaraciones", response_class=HTMLResponse)
    def portal_user_declaraciones(
        request: Request,
        issuer: dict = Depends(get_portal_issuer),
    ):
        declarations = get_declarations_for_issuer(issuer["id"])
        return _render_portal(
            request, issuer=issuer,
            template_name="portal_declaraciones.html",
            active_page="declaraciones",
            title="Mis declaraciones",
            extra={"declarations": declarations},
        )

    @router.get("/declaraciones/{declaration_id}", response_class=HTMLResponse)
    def portal_user_declaration_detail(
        request: Request,
        declaration_id: int,
        issuer: dict = Depends(get_portal_issuer),
    ):
        decl = get_declaration_by_id(declaration_id, issuer["id"])
        if not decl:
            return _render_portal(
                request, issuer=issuer,
                template_name="components/portal_error_inline.html",
                active_page="declaraciones",
                title="No encontrada",
                error="Declaracion no encontrada",
                status_code=404,
            )
        return _render_portal(
            request, issuer=issuer,
            template_name="portal_declaracion_detail.html",
            active_page="declaraciones",
            title=f"Declaracion — {decl.get('tipo', '')}",
            extra={"decl": decl},
        )


def _notify_user_of_declaration(decl: dict, issuer: dict):
    """Enqueue email notification when a declaration is validated."""
    try:
        from database import db_rows
        from services.email.queue import enqueue_send_email

        # Find the user's email for this issuer
        rows = db_rows(
            """SELECT u.email, u.id AS user_id
               FROM users u
               JOIN memberships m ON m.user_id = u.id
               WHERE m.issuer_id = ? AND m.role IN ('owner', 'accountant')
               ORDER BY m.role = 'owner' DESC LIMIT 1""",
            (decl["issuer_id"],),
        )
        if not rows:
            return
        user = rows[0]
        enqueue_send_email(
            to_email=user["email"],
            template="declaration_summary",
            context={
                "periodo": decl.get("periodo_ym", ""),
                "tipo_declaracion": decl.get("tipo", ""),
                "saldo_a_cargo": decl.get("saldo_a_cargo"),
                "saldo_a_favor": decl.get("saldo_a_favor"),
                "linea_captura": decl.get("linea_captura"),
                "fecha_vencimiento": decl.get("fecha_vencimiento"),
                "folio_acuse": decl.get("folio_acuse"),
                "brand_name": "ContaNeta",
            },
            email_type="declaration_summary",
            issuer_id=decl["issuer_id"],
            related_object_type="declaration",
            related_object_id=decl["id"],
        )
    except Exception as exc:
        logger.warning("Failed to enqueue declaration email: %s", exc)
