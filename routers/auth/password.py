"""Auth password routes: forgot password, reset password."""
import logging
import time

from fastapi import Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from routers.auth._helpers import base_url, forgot_error_message, reset_error_message
from services import email_sender, email_templates
from services import sanitize as sanitize_service
from services.auth import csrf as csrf_service
from services.auth import rate_limit as rate_limit_service
from services.auth import users
from services.auth import verification as verification_service

logger = logging.getLogger(__name__)


def register_password_routes(router, templates):
    """Register forgot-password and reset-password routes."""

    @router.get("/forgot", response_class=HTMLResponse)
    def forgot_page(request: Request, error: str | None = Query(None), sent: str | None = Query(None)):
        return templates.TemplateResponse(
            request,
            "forgot_password.html",
            {"error": forgot_error_message(error), "sent": sent == "1", "csrf_token": csrf_service.generate_csrf_token()},
        )

    @router.post("/forgot", response_class=RedirectResponse)
    def forgot_submit(request: Request, email: str = Form(""), csrf_token: str | None = Form(None)):
        token_val = (csrf_token or request.headers.get("X-CSRF-Token") or "").strip()
        if not csrf_service.verify_csrf_token(token_val):
            return RedirectResponse(url="/forgot?error=error", status_code=302)
        if rate_limit_service.is_rate_limited(request, "forgot"):
            time.sleep(2)
            return RedirectResponse(url="/forgot?error=error", status_code=302)
        email = sanitize_service.sanitize_email(email)
        if not email:
            return RedirectResponse(url="/forgot?error=email", status_code=302)
        user = users.get_user_by_email(email)
        if user:
            try:
                token = verification_service.create_password_reset(user["id"], expires_hours=2)
                reset_url = f"{base_url(request)}/reset-password?token={token}"
                body = f"Hola,\n\nPara restablecer tu contraseña abre este enlace (válido 2 h):\n{reset_url}\n\nSi no solicitaste esto, ignora el correo."
                html = email_templates.render_password_reset_email(reset_url=reset_url, expiry_minutes=120)
                email_sender.send_email(to=email, subject="Restablecer contraseña — ContaNeta", body_plain=body, body_html=html)
            except Exception as e:
                logger.exception("Forgot send reset email: %s", e)
        return RedirectResponse(url="/forgot?sent=1", status_code=302)

    @router.get("/reset-password", response_class=HTMLResponse)
    def reset_password_page(request: Request, token: str = Query(""), error: str | None = Query(None)):
        return templates.TemplateResponse(
            request,
            "reset_password.html",
            {"token": token, "error": reset_error_message(error), "csrf_token": csrf_service.generate_csrf_token()},
        )

    @router.post("/reset-password", response_class=RedirectResponse)
    def reset_password_submit(
        request: Request,
        token: str = Form(""),
        password: str = Form(""),
        password_confirm: str = Form(""),
        csrf_token: str | None = Form(None),
    ):
        token_val = (csrf_token or request.headers.get("X-CSRF-Token") or "").strip()
        if not csrf_service.verify_csrf_token(token_val):
            return RedirectResponse(url="/reset-password?error=error", status_code=302)
        if rate_limit_service.is_rate_limited(request, "reset"):
            time.sleep(2)
            url = f"/reset-password?token={token}&error=error" if token else "/reset-password?error=error"
            return RedirectResponse(url=url, status_code=302)
        if not token:
            return RedirectResponse(url="/login?error=invalid", status_code=302)
        user_id = verification_service.consume_password_reset_token(token)
        if not user_id:
            return RedirectResponse(url="/login?error=reset_expired", status_code=302)
        if not password or len(password) < 8:
            return RedirectResponse(url=f"/reset-password?token={token}&error=password", status_code=302)
        if password != password_confirm:
            return RedirectResponse(url=f"/reset-password?token={token}&error=mismatch", status_code=302)
        users.update_user_password(user_id, users.hash_password(password))
        return RedirectResponse(url="/login?msg=password_reset_ok", status_code=302)
