"""Auth login, logout, and issuer selection routes."""
import logging
import os
import time

from fastapi import Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from routers.auth._helpers import (
    DUMMY_HASH,
    clear_login_cooldown,
    google_login_url,
    facebook_login_url,
    login_email_cooldown,
    login_error_message,
    record_login_failure,
)
from services import audit, issuers
from services.action_log import log_action
from services.auth import csrf as csrf_service
from services.auth import rate_limit as rate_limit_service
from services.auth import session, users

logger = logging.getLogger(__name__)


def register_login_routes(router, templates):
    """Register login, logout, and issuer selection routes."""
    cookie_name = session.get_session_cookie_name()

    def _render_login(request: Request, error: str | None = None, success: str | None = None):
        if not success:
            msg = request.query_params.get("msg", "")
            verified = request.query_params.get("verified", "")
            if msg == "password_reset_ok":
                success = "Contraseña actualizada. Inicia sesión con tu nueva contraseña."
            elif verified == "1":
                success = "Correo verificado correctamente. Inicia sesión."
        return templates.TemplateResponse(
            request,
            "login.html",
            {
                "error": error,
                "success": success,
                "csrf_token": csrf_service.generate_csrf_token(),
                "google_login_url": google_login_url(request) or "#",
                "facebook_login_url": facebook_login_url(request) or "#",
                "google_oauth_configured": bool(os.getenv("GOOGLE_CLIENT_ID", "").strip()),
                "facebook_oauth_configured": bool(os.getenv("FACEBOOK_APP_ID", "").strip()),
            },
        )

    @router.get("/login", response_class=HTMLResponse)
    def login_page(request: Request, token: str = Query("", alias="token"), error: str | None = Query(None)):
        if token and token.strip():
            if rate_limit_service.is_rate_limited(request, "token_login", window_seconds=60.0, max_attempts=20):
                return _render_login(request, error="Demasiados intentos. Espera un minuto.")
            try:
                issuer = issuers.get_issuer_by_token(token.strip())
            except ValueError:
                return _render_login(request, error="Token inválido o inactivo.")
            resp = RedirectResponse(url="/portal/home", status_code=302)
            resp.set_cookie(
                cookie_name,
                session.sign_session(0, issuer["id"]),
                **session.session_cookie_params(request),
            )
            return resp
        return _render_login(request, error=login_error_message(error))

    @router.post("/login", response_class=RedirectResponse)
    def login_submit(
        request: Request,
        login_type: str = Form("credentials"),
        cred_type: str = Form("email"),
        email: str | None = Form(None),
        phone: str | None = Form(None),
        password: str = Form(...),
        csrf_token: str | None = Form(None),
        redirect_to: str | None = Form(None),
    ):
        try:
            token_val = (csrf_token or request.headers.get("X-CSRF-Token") or "").strip()
            logger.debug("LOGIN: cred_type=%s login_type=%s", cred_type, login_type)
            if not csrf_service.verify_csrf_token(token_val):
                logger.debug("LOGIN: CSRF FAILED")
                return RedirectResponse(url="/login?error=csrf", status_code=302)
            if rate_limit_service.is_rate_limited(request, "login"):
                logger.debug("LOGIN: rate limited")
                time.sleep(2)
                return RedirectResponse(url="/login?error=invalid", status_code=302)
            if login_type != "credentials" or not password:
                logger.debug("LOGIN: bad login_type or no password")
                return RedirectResponse(url="/login?error=invalid", status_code=302)
            email = (email or "").strip().lower() or None
            phone = (phone or "").strip() or None
            if cred_type == "phone":
                email = None
            else:
                phone = None
            logger.debug("LOGIN: credentials resolved, cred_type=%s", cred_type)
            if not email and not phone:
                logger.warning("Login: falta email o teléfono")
                return RedirectResponse(url="/login?error=email_or_phone", status_code=302)
            user = users.get_user_by_email_or_phone(email or phone)
            if not user:
                users.verify_password(password, DUMMY_HASH)
                logger.warning("LOGIN: user not found")
                if login_email_cooldown(email):
                    time.sleep(2)
                    return RedirectResponse(url="/login?error=cooldown", status_code=302)
                record_login_failure(email)
                return RedirectResponse(url="/login?error=bad_credentials", status_code=302)
            logger.debug("LOGIN: user found id=%s", user["id"])
            hashed = users.get_user_password_hash(user["id"])
            pwd_ok = users.verify_password(password, hashed) if hashed else False
            logger.debug("LOGIN: verify user_id=%s result=%s", user["id"], pwd_ok)
            if not hashed or not pwd_ok:
                logger.warning("Login: bad password for user_id=%s", user["id"])
                if login_email_cooldown(email):
                    time.sleep(2)
                    return RedirectResponse(url="/login?error=cooldown", status_code=302)
                record_login_failure(email)
                return RedirectResponse(url="/login?error=bad_credentials", status_code=302)
            logger.debug("LOGIN: password OK, setting session")
            clear_login_cooldown(email)
            # Track last login time for sync prioritization
            try:
                from database import db_execute
                db_execute(
                    "UPDATE users SET last_login_at = datetime('now') WHERE id = ?",
                    (user["id"],),
                )
            except Exception:
                pass  # non-critical
            memberships = users.get_memberships_for_user(user["id"])
            if not memberships:
                audit.log(action="login", user_id=user["id"], issuer_id=0, details="credentials", request=request)
                log_action(request, "login", user_id=user["id"], issuer_id=0)
                resp = RedirectResponse(url="/confirmar-perfil", status_code=302)
                resp.set_cookie(
                    cookie_name,
                    session.sign_session(user["id"], 0),
                    **session.session_cookie_params(request),
                )
                return resp
            if len(memberships) == 1:
                issuer_id = memberships[0]["issuer_id"]
                audit.log(action="login", user_id=user["id"], issuer_id=issuer_id, details="credentials", request=request)
                log_action(request, "login", user_id=user["id"], issuer_id=issuer_id)
                _redir = (redirect_to or "").strip()
                _target = _redir if _redir and _redir.startswith("/") and not _redir.startswith("//") else "/portal/home"
                resp = RedirectResponse(url=_target, status_code=302)
                resp.set_cookie(
                    cookie_name,
                    session.sign_session(user["id"], issuer_id),
                    **session.session_cookie_params(request),
                )
                return resp
            audit.log(action="login", user_id=user["id"], issuer_id=0, details="credentials", request=request)
            log_action(request, "login", user_id=user["id"], issuer_id=0)
            resp = RedirectResponse(url="/choose-issuer", status_code=302)
            resp.set_cookie(
                cookie_name,
                session.sign_session(user["id"], 0),
                **session.session_cookie_params(request),
            )
            return resp
        except Exception as e:
            logger.exception("Login error: %s", e)
            return RedirectResponse(url="/login?error=invalid", status_code=302)

    @router.get("/choose-issuer", response_class=HTMLResponse)
    def choose_issuer_page(request: Request):
        cookie_val = request.cookies.get(cookie_name)
        session_data = session.verify_session(cookie_val)
        if not session_data or session_data[0] == 0:
            return RedirectResponse(url="/login", status_code=302)
        user_id = session_data[0]
        memberships = users.get_memberships_for_user(user_id)
        if not memberships:
            return RedirectResponse(url="/confirmar-perfil", status_code=302)
        if len(memberships) == 1:
            resp = RedirectResponse(url="/portal/home", status_code=302)
            resp.set_cookie(
                cookie_name,
                session.sign_session(user_id, memberships[0]["issuer_id"]),
                **session.session_cookie_params(request),
            )
            return resp
        return templates.TemplateResponse(
            request,
            "choose_issuer.html",
            {"memberships": memberships, "csrf_token": csrf_service.generate_csrf_token()},
        )

    @router.post("/choose-issuer", response_class=RedirectResponse)
    def choose_issuer_submit(request: Request, issuer_id: int = Form(...), csrf_token: str | None = Form(None)):
        cookie_val = request.cookies.get(cookie_name)
        session_data = session.verify_session(cookie_val)
        if not session_data or session_data[0] == 0:
            return RedirectResponse(url="/login", status_code=302)
        token_val = (csrf_token or request.headers.get("X-CSRF-Token") or "").strip()
        if not csrf_service.verify_csrf_token(token_val):
            return RedirectResponse(url="/choose-issuer", status_code=302)
        user_id = session_data[0]
        mem = users.get_membership(user_id, issuer_id)
        if not mem:
            return RedirectResponse(url="/choose-issuer", status_code=302)
        resp = RedirectResponse(url="/portal/home", status_code=302)
        resp.set_cookie(
            cookie_name,
            session.sign_session(user_id, issuer_id),
            **session.session_cookie_params(request),
        )
        return resp

    @router.get("/logout")
    @router.post("/logout")
    def logout(request: Request):
        cookie_val = request.cookies.get(cookie_name)
        session_data = session.verify_session(cookie_val)
        if session_data and len(session_data) >= 2:
            uid, iid = session_data[0], session_data[1]
            audit.log(
                action="logout",
                user_id=uid if uid else None,
                issuer_id=iid if iid else None,
                details="",
                request=request,
            )
            log_action(request, "logout", user_id=uid, issuer_id=iid)
        resp = RedirectResponse(url="/login", status_code=302)
        cookie_params = session.session_cookie_params(request)
        resp.delete_cookie(
            cookie_name,
            path=cookie_params.get("path", "/"),
            samesite=cookie_params.get("samesite", "lax"),
            secure=cookie_params.get("secure", False),
        )
        return resp
