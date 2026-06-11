"""Auth registration routes: signup, register, verify-email."""
import logging
import os
import time
from urllib.parse import urlencode

from fastapi import Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from routers.auth._helpers import (
    base_url,
    facebook_login_url,
    google_login_url,
    signup_error_message,
)
from services import audit, email_sender, email_templates, issuers
from services import sanitize as sanitize_service
from services.auth import csrf as csrf_service
from services.auth import rate_limit as rate_limit_service
from services.auth import session, users
from services.auth import verification as verification_service

logger = logging.getLogger(__name__)


def register_register_routes(router, templates):
    """Register signup, register, and verify-email routes."""
    cookie_name = session.get_session_cookie_name()

    @router.get("/register", response_class=RedirectResponse)
    def register_redirect(request: Request):
        return RedirectResponse(url="/signup", status_code=302)

    @router.get("/signup", response_class=HTMLResponse)
    def signup_page(request: Request, error: str | None = Query(None), email: str | None = Query(None), phone: str | None = Query(None), lt: str | None = Query(None)):
        return templates.TemplateResponse(
            request,
            "signup.html",
            {
                "error": signup_error_message(error),
                "csrf_token": csrf_service.generate_csrf_token(),
                "google_login_url": google_login_url(request) or "#",
                "facebook_login_url": facebook_login_url(request) or "#",
                "google_oauth_configured": bool(os.getenv("GOOGLE_CLIENT_ID", "").strip()),
                "facebook_oauth_configured": bool(os.getenv("FACEBOOK_APP_ID", "").strip()),
                "prev_email": email or "",
                "prev_phone": phone or "",
                "prev_login_type": lt or "email",
            },
        )

    @router.post("/signup", response_class=RedirectResponse)
    def signup_submit(
        request: Request,
        login_type: str = Form("email"),
        email: str | None = Form(None),
        phone: str | None = Form(None),
        password: str = Form(...),
        password_confirm: str | None = Form(None),
        accept_terms: str | None = Form(None),
        authorize_firm: str | None = Form(None),
        csrf_token: str | None = Form(None),
    ):
        token_val = (csrf_token or request.headers.get("X-CSRF-Token") or "").strip()
        if not csrf_service.verify_csrf_token(token_val):
            return RedirectResponse(url="/signup?error=terms", status_code=302)
        if rate_limit_service.is_rate_limited(request, "register"):
            time.sleep(2)
            return RedirectResponse(url="/signup?error=error", status_code=302)
        if accept_terms != "on":
            return RedirectResponse(url="/signup?error=terms", status_code=302)
        email = (email or "").strip().lower() or None
        phone = (phone or "").strip() or None
        if login_type == "phone":
            email = None
        else:
            phone = None

        # Build redirect base with preserved fields
        _keep = {}
        if email:
            _keep["email"] = email
        if phone:
            _keep["phone"] = phone
        if login_type == "phone":
            _keep["lt"] = "phone"

        def _err_url(code: str) -> str:
            params = {"error": code, **_keep}
            return f"/signup?{urlencode(params)}"

        if not email and not phone:
            return RedirectResponse(url=_err_url("email_or_phone"), status_code=302)
        if not password or len(password) < 8:
            return RedirectResponse(url=_err_url("password"), status_code=302)
        pw_err = users.validate_password_strength(password)
        if pw_err:
            return RedirectResponse(url=_err_url("password"), status_code=302)
        if password != password_confirm:
            return RedirectResponse(url=_err_url("password_mismatch"), status_code=302)
        if email and users.get_user_by_email(email):
            return RedirectResponse(url=_err_url("email_exists"), status_code=302)
        if phone and users.get_user_by_phone(phone):
            return RedirectResponse(url=_err_url("phone_exists"), status_code=302)
        try:
            user = users.create_user(email=email, phone=phone, password_hash=users.hash_password(password))
        except Exception as e:
            logger.exception("Signup create_user: %s", e)
            return RedirectResponse(url="/signup?error=error", status_code=302)
        resp = RedirectResponse(url="/confirmar-perfil", status_code=302)
        resp.set_cookie(
            cookie_name,
            session.sign_session(user["id"], 0),
            **session.session_cookie_params(request),
        )
        return resp

    @router.post("/auth/signup", response_class=RedirectResponse)
    def auth_signup_submit(
        request: Request,
        email: str = Form(...),
        password: str = Form(...),
        phone: str | None = Form(None),
        rfc: str | None = Form(None),
        razon_social: str | None = Form(None),
        regimen_fiscal: str = Form("616"),
        cp: str | None = Form(None),
        csrf_token: str | None = Form(None),
    ):
        token_val = (csrf_token or request.headers.get("X-CSRF-Token") or "").strip()
        if not csrf_service.verify_csrf_token(token_val):
            return RedirectResponse(url="/signup?error=error", status_code=302)
        if rate_limit_service.is_rate_limited(request, "register"):
            time.sleep(2)
            return RedirectResponse(url="/signup?error=error", status_code=302)
        email = sanitize_service.sanitize_email(email)
        if not email:
            return RedirectResponse(url="/signup?error=required", status_code=302)
        # Phone is required for outreach/onboarding. Normalize to digits only.
        phone_clean = "".join(ch for ch in (phone or "") if ch.isdigit())
        if not phone_clean or len(phone_clean) < 10:
            return RedirectResponse(url="/signup?error=phone_required", status_code=302)
        if not password or len(password) < 8:
            return RedirectResponse(url="/signup?error=password", status_code=302)
        pw_err = users.validate_password_strength(password)
        if pw_err:
            return RedirectResponse(url="/signup?error=password", status_code=302)
        # RFC + razón social + CP + régimen: TODOS opcionales en signup.
        # Algunos leads no tienen sus datos SAT al día — los completan después
        # en /portal/settings → tab "Datos fiscales". El push a Facturapi se
        # hace automáticamente cuando completan esos campos.
        rfc = sanitize_service.sanitize_rfc(rfc) if rfc else None
        razon_social = (razon_social or "").strip()[:200] or None
        cp = sanitize_service.sanitize_cp(cp)
        if cp is not None and len(cp) != 5:
            cp = None
        if users.get_user_by_email(email):
            return RedirectResponse(url="/signup?error=error", status_code=302)
        display_name = razon_social or email.split("@")[0].title()
        try:
            user = users.create_user(
                email=email,
                phone=phone_clean,
                password_hash=users.hash_password(password),
                name=display_name,
            )
        except Exception as e:
            logger.exception("Signup create_user: %s", e)
            return RedirectResponse(url="/signup?error=error", status_code=302)
        try:
            issuer_id, _ = issuers.create_issuer_with_token(
                rfc=rfc or "PENDIENTE",
                razon_social=razon_social or display_name,
                regimen_fiscal=(regimen_fiscal or "").strip() or None,
            )
            users.add_membership(user["id"], issuer_id, "owner")
        except Exception as e:
            logger.exception("Signup create_issuer/membership: %s", e)
            return RedirectResponse(url="/signup?error=error", status_code=302)
        audit.log(
            action="register",
            user_id=user["id"],
            issuer_id=issuer_id,
            details=f"email={email[:50]} rfc={rfc or 'PENDIENTE'}",
            request=request,
        )
        try:
            token = verification_service.create_email_verification(user["id"], expires_hours=24)
            verify_url = f"{base_url(request)}/verify-email?token={token}"
            body = f"Hola,\n\nVerifica tu correo abriendo este enlace (válido 24 h):\n{verify_url}\n\nSi no creaste esta cuenta, ignora este mensaje."
            html = email_templates.render_welcome_email(user_name=name or email.split("@")[0], login_url=verify_url)
            email_sender.send_email(to=email, subject="Verifica tu correo — ContaNeta", body_plain=body, body_html=html)
        except Exception as e:
            logger.exception("Signup send verification email: %s", e)
        resp = RedirectResponse(url="/portal/home", status_code=302)
        resp.set_cookie(
            cookie_name,
            session.sign_session(user["id"], issuer_id),
            **session.session_cookie_params(request),
        )
        return resp

    @router.post("/auth/register", response_class=RedirectResponse)
    def auth_register_submit(
        request: Request,
        email: str = Form(...),
        password: str = Form(...),
        rfc: str = Form(...),
        razon_social: str = Form(...),
        regimen_fiscal: str = Form("616"),
        cp: str | None = Form(None),
        csrf_token: str | None = Form(None),
    ):
        token_val = (csrf_token or request.headers.get("X-CSRF-Token") or "").strip()
        if not csrf_service.verify_csrf_token(token_val):
            return RedirectResponse(url="/signup?error=error", status_code=302)
        if rate_limit_service.is_rate_limited(request, "register"):
            time.sleep(2)
            return RedirectResponse(url="/signup?error=error", status_code=302)
        email = sanitize_service.sanitize_email(email)
        if not email:
            return RedirectResponse(url="/signup?error=required", status_code=302)
        if not password or len(password) < 8:
            return RedirectResponse(url="/signup?error=password", status_code=302)
        pw_err = users.validate_password_strength(password)
        if pw_err:
            return RedirectResponse(url="/signup?error=password", status_code=302)
        rfc = sanitize_service.sanitize_rfc(rfc)
        razon_social = (razon_social or "").strip()[:200]
        if not rfc or not razon_social:
            return RedirectResponse(url="/signup?error=required", status_code=302)
        cp = sanitize_service.sanitize_cp(cp)
        if cp is not None and len(cp) != 5:
            cp = None
        if users.get_user_by_email(email):
            return RedirectResponse(url="/signup?error=error", status_code=302)
        try:
            user = users.create_user(
                email=email,
                password_hash=users.hash_password(password),
                name=razon_social,
            )
        except Exception as e:
            logger.exception("Register create_user: %s", e)
            return RedirectResponse(url="/signup?error=error", status_code=302)
        try:
            issuer_id, _ = issuers.create_issuer_with_token(
                rfc=rfc,
                razon_social=razon_social,
                regimen_fiscal=(regimen_fiscal or "").strip() or None,
            )
            users.add_membership(user["id"], issuer_id, "owner")
        except Exception as e:
            logger.exception("Register create_issuer/membership: %s", e)
            return RedirectResponse(url="/signup?error=error", status_code=302)
        audit.log(
            action="register",
            user_id=user["id"],
            issuer_id=issuer_id,
            details=f"email={email[:50]} rfc={rfc}",
            request=request,
        )
        try:
            token = verification_service.create_email_verification(user["id"], expires_hours=24)
            verify_url = f"{base_url(request)}/verify-email?token={token}"
            body = f"Hola,\n\nVerifica tu correo: {verify_url}\n\nVálido 24 h."
            html = email_templates.render_welcome_email(user_name=name or email.split("@")[0], login_url=verify_url)
            email_sender.send_email(to=email, subject="Verifica tu correo — ContaNeta", body_plain=body, body_html=html)
        except Exception as e:
            logger.exception("Register send verification: %s", e)
        resp = RedirectResponse(url="/portal/home", status_code=302)
        resp.set_cookie(
            cookie_name,
            session.sign_session(user["id"], issuer_id),
            **session.session_cookie_params(request),
        )
        return resp

    @router.get("/verify-email", response_class=RedirectResponse)
    def verify_email_page(request: Request, token: str = Query("")):
        user_id = verification_service.verify_email_token(token)
        if user_id:
            return RedirectResponse(url="/login?verified=1", status_code=302)
        return RedirectResponse(url="/login?verified=0", status_code=302)
