"""Admin impersonation, sentry test, and test email routes."""
import logging

from fastapi import Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from routers.admin._deps import _get_session_user_and_issuer, require_admin
from services import audit, issuers
from services.action_log import log_action
from services.auth import csrf as csrf_service
from services.auth import session, users

logger = logging.getLogger(__name__)


class ImpersonateBody(BaseModel):
    issuer_id: int | None = None
    rfc: str | None = None


def register_impersonate_routes(router, templates):
    """Register admin impersonation and dev tool routes."""

    def _do_impersonate(request: Request, user_id: int, current_issuer_id: int, target_issuer_id: int | None, rfc: str | None):
        target_issuer = None
        if target_issuer_id is not None:
            target_issuer = issuers.get_issuer_by_id(target_issuer_id)
        if target_issuer is None and rfc:
            target_issuer = issuers.get_issuer_by_rfc((rfc or "").strip())
        if not target_issuer:
            raise HTTPException(status_code=400, detail="Issuer no encontrado (issuer_id o rfc válido)")
        # Verify admin has membership in target issuer (prevent cross-tenant escalation)
        mem = users.get_membership(user_id, target_issuer["id"])
        if not mem:
            logger.warning("Impersonation denied: user_id=%s has no membership for target issuer_id=%s", user_id, target_issuer["id"])
            raise HTTPException(status_code=403, detail="No tienes acceso a este emisor.")
        audit.log(
            action="impersonate_start",
            user_id=user_id,
            issuer_id=current_issuer_id,
            target_issuer_id=target_issuer["id"],
            details=f"target_issuer_id={target_issuer['id']} rfc={target_issuer.get('rfc') or ''}",
            request=request,
        )
        # obligatorio: action_log también (sin romper si falla)
        try:
            log_action(request, "impersonate_start", user_id=user_id, issuer_id=current_issuer_id, target_issuer_id=target_issuer["id"])
        except Exception:
            pass
        cookie_val = session.sign_session(
            user_id,
            target_issuer["id"],
            restore_issuer_id=current_issuer_id,
        )
        response = RedirectResponse(url="/portal/home", status_code=302)
        response.set_cookie(
            session.get_session_cookie_name(),
            cookie_val,
            **session.session_cookie_params(request),
        )
        return response

    @router.post("/impersonate")
    def admin_impersonate(
        request: Request,
        body: ImpersonateBody,
        _admin: tuple[int, int, int | None] = Depends(require_admin),
    ):
        csrf_service.verify_api_csrf(request)
        user_id, current_issuer_id, _ = _admin
        return _do_impersonate(request, user_id, current_issuer_id, body.issuer_id, body.rfc)

    # GET /impersonate removed — CSRF risk. Use POST only.

    @router.post("/impersonate/{issuer_id:int}", response_class=RedirectResponse)
    def admin_impersonate_post(
        request: Request,
        issuer_id: int,
        csrf_token: str | None = Form(None),
        _admin: tuple[int, int, int | None] = Depends(require_admin),
    ):
        token_val = (csrf_token or request.headers.get("X-CSRF-Token") or "").strip()
        if not csrf_service.verify_csrf_token(token_val):
            raise HTTPException(status_code=403, detail="Token CSRF inválido o expirado")
        user_id, current_issuer_id, _ = _admin
        return _do_impersonate(request, user_id, current_issuer_id, issuer_id, None)

    @router.post("/impersonate-form", response_class=RedirectResponse)
    def admin_impersonate_form(
        request: Request,
        issuer_id: int | None = Form(None),
        rfc: str | None = Form(None),
        csrf_token: str | None = Form(None),
        _admin: tuple[int, int, int | None] = Depends(require_admin),
    ):
        token_val = (csrf_token or request.headers.get("X-CSRF-Token") or "").strip()
        if not csrf_service.verify_csrf_token(token_val):
            raise HTTPException(status_code=403, detail="Token CSRF inválido o expirado")
        user_id, current_issuer_id, _ = _admin
        return _do_impersonate(request, user_id, current_issuer_id, issuer_id, rfc)

    @router.post("/stop-impersonate")
    def admin_stop_impersonate(request: Request, csrf_token: str | None = Form(None)):
        token_val = (csrf_token or request.headers.get("X-CSRF-Token") or "").strip()
        if not csrf_service.verify_csrf_token(token_val):
            raise HTTPException(status_code=403, detail="Token CSRF inválido o expirado")
        user_id, _current_issuer_id, restore_issuer_id = _get_session_user_and_issuer(request)
        if restore_issuer_id is None:
            raise HTTPException(status_code=400, detail="No estás en modo impersonación")
        audit.log(
            action="impersonate_stop",
            user_id=user_id,
            issuer_id=_current_issuer_id,
            target_issuer_id=restore_issuer_id,
            details=f"restored_issuer_id={restore_issuer_id}",
            request=request,
        )
        try:
            log_action(request, "impersonate_stop", user_id=user_id, issuer_id=_current_issuer_id, target_issuer_id=restore_issuer_id)
        except Exception:
            pass
        cookie_val = session.sign_session(user_id, restore_issuer_id, restore_issuer_id=None)
        response = RedirectResponse(url="/portal/home", status_code=302)
        response.set_cookie(
            session.get_session_cookie_name(),
            cookie_val,
            **session.session_cookie_params(request),
        )
        return response

    @router.get("/sentry-test")
    def admin_sentry_test(
        _admin: tuple = Depends(require_admin),
    ):
        """Intentional exception to verify Sentry integration. Admin only."""
        raise RuntimeError("Sentry test: intentional error from /admin/sentry-test")

    @router.post("/test-email")
    def admin_test_email(
        request: Request,
        _admin: tuple = Depends(require_admin),
    ):
        """Send a test email to the current admin user."""
        from services import email_sender, email_templates
        from services.auth.users import get_user_by_id
        admin_user_id = _admin[0]
        user = get_user_by_id(admin_user_id)
        if not user or not user.get("email"):
            return {"ok": False, "error": "No se encontró email del admin"}
        to = user["email"]
        if not email_sender.is_configured():
            return {"ok": False, "error": "SMTP no configurado. Define SMTP_HOST, SMTP_USER, SMTP_PASSWORD en .env"}
        html = email_templates.render_welcome_email(
            user_name=user.get("name") or to.split("@")[0],
            login_url=f"{request.base_url}portal/home",
        )
        plain = f"Correo de prueba desde ContaNeta. Si ves esto, SMTP funciona.\n\nIr al portal: {request.base_url}portal/home"
        sent = email_sender.send_email(to=to, subject="[TEST] Correo de prueba — ContaNeta", body_plain=plain, body_html=html)
        return {"ok": sent, "sent_to": to[:50], "smtp_host": email_sender.SMTP_HOST}
