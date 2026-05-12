"""Rutas de autenticación: login, signup, OAuth, confirmar perfil, onboarding, register."""
import logging
import os
import time
from collections import defaultdict
from urllib.parse import quote

from fastapi import APIRouter, Request, Form, Query, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
import httpx

from config import _env_path, DEV_MODE
from database import db
from services import issuers, audit, action_log
from services.auth import session, users, csrf as csrf_service
from services.action_log import log_action
from services.auth import rate_limit as rate_limit_service
from services import sanitize as sanitize_service
from services.auth import verification as verification_service
from services import email_sender

logger = logging.getLogger(__name__)

# Dummy bcrypt hash for constant-time login (prevents timing-based user enumeration)
_DUMMY_HASH = "$2b$12$U6hZVXXPMyR82NvkOKCr2O4o/torbd/ZHVpPFSDM09kGjGX20spOW"

# Cooldown por email: desactivado (no bloquear por intentos fallidos)
_LOGIN_FAILURES_BY_EMAIL: dict[str, list[float]] = defaultdict(list)
_EMAIL_FAILURES_WINDOW = 900.0
_EMAIL_MAX_FAILURES = 5
_EMAIL_COOLDOWN_SECONDS = 900  # 15 minutos
_EMAIL_COOLDOWN_UNTIL: dict[str, float] = {}


def _login_email_cooldown(email: str | None) -> bool:
    """True si el email está en cooldown tras 5 fallos de login."""
    if not email or not email.strip():
        return False
    e = (email or "").strip().lower()
    now = time.time()
    if now < _EMAIL_COOLDOWN_UNTIL.get(e, 0):
        return True
    return False


def _record_login_failure(email: str | None) -> None:
    """Registra un fallo de login para el email; si llega a 5, activa cooldown."""
    if not email or not email.strip():
        return
    e = (email or "").strip().lower()
    now = time.time()
    _LOGIN_FAILURES_BY_EMAIL[e] = [t for t in _LOGIN_FAILURES_BY_EMAIL[e] if now - t < _EMAIL_FAILURES_WINDOW]
    _LOGIN_FAILURES_BY_EMAIL[e].append(now)
    if len(_LOGIN_FAILURES_BY_EMAIL[e]) >= _EMAIL_MAX_FAILURES:
        _EMAIL_COOLDOWN_UNTIL[e] = now + _EMAIL_COOLDOWN_SECONDS


def _login_error_message(code: str | None) -> str | None:
    # Mensajes genéricos: no revelar "email existe" / "email no existe"
    msgs = {
        "invalid": "Datos inválidos. Intenta de nuevo.",
        "cooldown": "Demasiados intentos. Espera 15 minutos antes de intentar de nuevo.",
        "csrf": "La sesión de la página expiró. Recarga la página (F5) e intenta de nuevo.",
        "email_or_phone": "Indica tu correo o teléfono.",
        "bad_credentials": "Datos inválidos. Intenta de nuevo.",
        "oauth": "No se pudo iniciar sesión con la red social. Intenta de nuevo.",
        "oauth_config": "Inicio de sesión con red social no configurado.",
    }
    return msgs.get(code or "", None)


def _signup_error_message(code: str | None) -> str | None:
    msgs = {
        "terms": "Debes aceptar los términos y el aviso de privacidad.",
        "email_or_phone": "Indica tu correo o teléfono.",
        "password": "La contraseña debe tener al menos 8 caracteres.",
        "password_mismatch": "Las contraseñas no coinciden.",
        "email_exists": "Ya existe una cuenta con este correo. Intenta iniciar sesión o usa otro correo.",
        "phone_exists": "Ya existe una cuenta con este teléfono. Intenta iniciar sesión o usa otro número.",
        "error": "No se pudo crear la cuenta. Intenta de nuevo.",
    }
    return msgs.get(code or "", None)


def _register_error_message(code: str | None) -> str | None:
    # Genérico: no decir "email ya existe"
    msgs = {
        "error": "No se pudo crear la cuenta. Intenta de nuevo.",
        "password": "La contraseña debe tener al menos 8 caracteres.",
        "required": "Completa todos los campos obligatorios.",
    }
    return msgs.get(code or "", None)


def _forgot_error_message(code: str | None) -> str | None:
    msgs = {
        "error": "No se pudo enviar el correo. Intenta más tarde.",
        "email": "Indica tu correo electrónico.",
    }
    return msgs.get(code or "", None)


def _reset_error_message(code: str | None) -> str | None:
    msgs = {
        "error": "El enlace no es válido o ha expirado. Solicita uno nuevo.",
        "password": "La contraseña debe tener al menos 8 caracteres.",
        "mismatch": "Las contraseñas no coinciden.",
    }
    return msgs.get(code or "", None)


def _base_url(request: Request) -> str:
    base = os.getenv("SITE_URL", "").strip()
    if base:
        return base.rstrip("/")
    return str(request.base_url).rstrip("/")


def _oauth_redirect_base(request: Request) -> str:
    base = os.getenv("SITE_URL", "").strip()
    if base:
        return base.rstrip("/")
    return str(request.base_url).rstrip("/")


def _google_login_url(request: Request) -> str:
    cid = os.getenv("GOOGLE_CLIENT_ID", "").strip()
    if not cid:
        return ""
    base = _oauth_redirect_base(request)
    redirect_uri = quote(f"{base}/auth/google/callback", safe="")
    scopes = "openid%20email%20profile%20https://www.googleapis.com/auth/user.phonenumbers.read"
    return f"https://accounts.google.com/o/oauth2/v2/auth?client_id={cid}&redirect_uri={redirect_uri}&response_type=code&scope={scopes}"


def _facebook_login_url(request: Request) -> str:
    app_id = os.getenv("FACEBOOK_APP_ID", "").strip()
    if not app_id:
        return ""
    base = _oauth_redirect_base(request)
    redirect_uri = quote(f"{base}/auth/facebook/callback", safe="")
    return f"https://www.facebook.com/v18.0/dialog/oauth?client_id={app_id}&redirect_uri={redirect_uri}&scope=email,public_profile"


def get_auth_router(templates):
    router = APIRouter()
    cookie_name = session.get_session_cookie_name()

    def _render_login(request: Request, error: str | None = None, success: str | None = None):
        # Flash messages from query params
        if not success:
            msg = request.query_params.get("msg", "")
            verified = request.query_params.get("verified", "")
            if msg == "password_reset_ok":
                success = "Contraseña actualizada. Inicia sesión con tu nueva contraseña."
            elif verified == "1":
                success = "Correo verificado correctamente. Inicia sesión."
        return templates.TemplateResponse(
            "login.html",
            {
                "request": request,
                "error": error,
                "success": success,
                "csrf_token": csrf_service.generate_csrf_token(),
                "google_login_url": _google_login_url(request) or "#",
                "facebook_login_url": _facebook_login_url(request) or "#",
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
        return _render_login(request, error=_login_error_message(error))

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
                # Constant-time: run bcrypt against dummy hash to prevent timing enumeration
                users.verify_password(password, _DUMMY_HASH)
                logger.warning("LOGIN: user not found")
                if _login_email_cooldown(email):
                    time.sleep(2)
                    return RedirectResponse(url="/login?error=cooldown", status_code=302)
                _record_login_failure(email)
                return RedirectResponse(url="/login?error=bad_credentials", status_code=302)
            logger.debug("LOGIN: user found id=%s", user["id"])
            hashed = users.get_user_password_hash(user["id"])
            pwd_ok = users.verify_password(password, hashed) if hashed else False
            logger.debug("LOGIN: verify user_id=%s result=%s", user["id"], pwd_ok)
            if not hashed or not pwd_ok:
                logger.warning("Login: bad password for user_id=%s", user["id"])
                if _login_email_cooldown(email):
                    time.sleep(2)
                    return RedirectResponse(url="/login?error=cooldown", status_code=302)
                _record_login_failure(email)
                return RedirectResponse(url="/login?error=bad_credentials", status_code=302)
            logger.debug("LOGIN: password OK, setting session")
            # Login correcto: quitar cooldown de este email para que no quede bloqueado
            if email:
                _EMAIL_COOLDOWN_UNTIL.pop(email, None)
                _LOGIN_FAILURES_BY_EMAIL.pop(email, None)
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
                # Redirect to original page if available and safe (starts with /)
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

    @router.get("/register", response_class=RedirectResponse)
    def register_redirect(request: Request):
        return RedirectResponse(url="/signup", status_code=302)

    # /signup GET is registered later (signup_page) with social login support

    @router.post("/auth/signup", response_class=RedirectResponse)
    def auth_signup_submit(
        request: Request,
        email: str = Form(...),
        password: str = Form(...),
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
        if not password or len(password) < 8:
            return RedirectResponse(url="/signup?error=password", status_code=302)
        pw_err = users.validate_password_strength(password)
        if pw_err:
            return RedirectResponse(url="/signup?error=password", status_code=302)
        # RFC is optional — allow signup without fiscal data
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
            verify_url = f"{_base_url(request)}/verify-email?token={token}"
            body = f"Hola,\n\nVerifica tu correo abriendo este enlace (válido 24 h):\n{verify_url}\n\nSi no creaste esta cuenta, ignora este mensaje."
            email_sender.send_email(to=email, subject="Verifica tu correo — ContaNeta", body_plain=body)
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
            verify_url = f"{_base_url(request)}/verify-email?token={token}"
            body = f"Hola,\n\nVerifica tu correo: {verify_url}\n\nVálido 24 h."
            email_sender.send_email(to=email, subject="Verifica tu correo — ContaNeta", body_plain=body)
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

    @router.get("/forgot", response_class=HTMLResponse)
    def forgot_page(request: Request, error: str | None = Query(None), sent: str | None = Query(None)):
        return templates.TemplateResponse(
            "forgot_password.html",
            {"request": request, "error": _forgot_error_message(error), "sent": sent == "1", "csrf_token": csrf_service.generate_csrf_token()},
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
                reset_url = f"{_base_url(request)}/reset-password?token={token}"
                body = f"Hola,\n\nPara restablecer tu contraseña abre este enlace (válido 2 h):\n{reset_url}\n\nSi no solicitaste esto, ignora el correo."
                email_sender.send_email(to=email, subject="Restablecer contraseña — ContaNeta", body_plain=body)
            except Exception as e:
                logger.exception("Forgot send reset email: %s", e)
        return RedirectResponse(url="/forgot?sent=1", status_code=302)

    @router.get("/reset-password", response_class=HTMLResponse)
    def reset_password_page(request: Request, token: str = Query(""), error: str | None = Query(None)):
        return templates.TemplateResponse(
            "reset_password.html",
            {"request": request, "token": token, "error": _reset_error_message(error), "csrf_token": csrf_service.generate_csrf_token()},
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
            "choose_issuer.html",
            {"request": request, "memberships": memberships, "csrf_token": csrf_service.generate_csrf_token()},
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
        # Borrar cookie con los mismos parámetros que se usaron al crearla
        cookie_params = session.session_cookie_params(request)
        resp.delete_cookie(
            cookie_name,
            path=cookie_params.get("path", "/"),
            samesite=cookie_params.get("samesite", "lax"),
            secure=cookie_params.get("secure", False),
        )
        return resp

    @router.get("/auth/google/callback", response_class=RedirectResponse)
    async def auth_google_callback(request: Request, code: str | None = Query(None), error: str | None = Query(None)):
        if error or not code:
            return RedirectResponse(url="/login?error=oauth", status_code=302)
        base = _oauth_redirect_base(request)
        client_id = os.getenv("GOOGLE_CLIENT_ID", "").strip()
        client_secret = os.getenv("GOOGLE_CLIENT_SECRET", "").strip()
        if not client_id or not client_secret:
            return RedirectResponse(url="/login?error=oauth_config", status_code=302)
        async with httpx.AsyncClient() as client:
            token_res = await client.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "code": code,
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "redirect_uri": f"{base}/auth/google/callback",
                    "grant_type": "authorization_code",
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        if token_res.status_code != 200:
            logger.warning("Google token exchange failed: status=%s", token_res.status_code)
            return RedirectResponse(url="/login?error=oauth", status_code=302)
        try:
            token_data = token_res.json()
            access_token = token_data.get("access_token")
        except Exception:
            return RedirectResponse(url="/login?error=oauth", status_code=302)
        if not access_token:
            return RedirectResponse(url="/login?error=oauth", status_code=302)
        async with httpx.AsyncClient() as client:
            user_res = await client.get(
                "https://www.googleapis.com/oauth2/v2/userinfo",
                headers={"Authorization": f"Bearer {access_token}"},
            )
        if user_res.status_code != 200:
            return RedirectResponse(url="/login?error=oauth", status_code=302)
        try:
            user_info = user_res.json()
            oauth_id = user_info.get("id") or user_info.get("sub")
            email = (user_info.get("email") or "").strip().lower() or None
            name_oauth = (user_info.get("name") or "").strip()
            if not name_oauth:
                given = (user_info.get("given_name") or "").strip()
                family = (user_info.get("family_name") or "").strip()
                name_oauth = f"{given} {family}".strip() or None
            else:
                name_oauth = name_oauth or None
        except Exception:
            return RedirectResponse(url="/login?error=oauth", status_code=302)
        if not oauth_id:
            return RedirectResponse(url="/login?error=oauth", status_code=302)
        phone_oauth = None
        try:
            async with httpx.AsyncClient() as ac:
                people_res = await ac.get(
                    "https://people.googleapis.com/v1/people/me?personFields=phoneNumbers",
                    headers={"Authorization": f"Bearer {access_token}"},
                )
            if people_res.status_code == 200:
                data = people_res.json()
                for p in (data.get("phoneNumbers") or []):
                    val = (p.get("value") or "").strip()
                    if val:
                        phone_oauth = val
                        break
        except Exception:
            pass
        user = users.get_or_create_user_by_oauth("google", oauth_id, email=email, name=name_oauth, phone=phone_oauth)
        memberships = users.get_memberships_for_user(user["id"])
        if not memberships:
            resp = RedirectResponse(url="/confirmar-perfil", status_code=302)
            resp.set_cookie(
                cookie_name,
                session.sign_session(user["id"], 0),
                **session.session_cookie_params(request),
            )
            return resp
        if len(memberships) == 1:
            resp = RedirectResponse(url="/portal/home", status_code=302)
            resp.set_cookie(
                cookie_name,
                session.sign_session(user["id"], memberships[0]["issuer_id"]),
                **session.session_cookie_params(request),
            )
            return resp
        resp = RedirectResponse(url="/choose-issuer", status_code=302)
        resp.set_cookie(
            cookie_name,
            session.sign_session(user["id"], 0),
            **session.session_cookie_params(request),
        )
        return resp

    @router.get("/auth/facebook/callback", response_class=RedirectResponse)
    async def auth_facebook_callback(request: Request, code: str | None = Query(None), error: str | None = Query(None)):
        if error or not code:
            return RedirectResponse(url="/login?error=oauth", status_code=302)
        base = _oauth_redirect_base(request)
        app_id = os.getenv("FACEBOOK_APP_ID", "").strip()
        app_secret = os.getenv("FACEBOOK_APP_SECRET", "").strip()
        if not app_id or not app_secret:
            return RedirectResponse(url="/login?error=oauth_config", status_code=302)
        async with httpx.AsyncClient() as client:
            token_res = await client.get(
                "https://graph.facebook.com/v18.0/oauth/access_token",
                params={
                    "client_id": app_id,
                    "client_secret": app_secret,
                    "redirect_uri": f"{base}/auth/facebook/callback",
                    "code": code,
                },
            )
        if token_res.status_code != 200:
            logger.warning("Facebook token exchange failed: status=%s", token_res.status_code)
            return RedirectResponse(url="/login?error=oauth", status_code=302)
        try:
            token_data = token_res.json()
            access_token = token_data.get("access_token")
        except Exception:
            return RedirectResponse(url="/login?error=oauth", status_code=302)
        if not access_token:
            return RedirectResponse(url="/login?error=oauth", status_code=302)
        async with httpx.AsyncClient() as client:
            user_res = await client.get(
                "https://graph.facebook.com/me",
                params={"fields": "id,email,name", "access_token": access_token},
            )
        if user_res.status_code != 200:
            return RedirectResponse(url="/login?error=oauth", status_code=302)
        try:
            user_info = user_res.json()
            oauth_id = user_info.get("id")
            email = (user_info.get("email") or "").strip().lower() or None
        except Exception:
            return RedirectResponse(url="/login?error=oauth", status_code=302)
        if not oauth_id:
            return RedirectResponse(url="/login?error=oauth", status_code=302)
        name_oauth = (user_info.get("name") or "").strip() or None
        user = users.get_or_create_user_by_oauth("facebook", oauth_id, email=email, name=name_oauth)
        memberships = users.get_memberships_for_user(user["id"])
        if not memberships:
            resp = RedirectResponse(url="/confirmar-perfil", status_code=302)
            resp.set_cookie(
                cookie_name,
                session.sign_session(user["id"], 0),
                **session.session_cookie_params(request),
            )
            return resp
        if len(memberships) == 1:
            resp = RedirectResponse(url="/portal/home", status_code=302)
            resp.set_cookie(
                cookie_name,
                session.sign_session(user["id"], memberships[0]["issuer_id"]),
                **session.session_cookie_params(request),
            )
            return resp
        resp = RedirectResponse(url="/choose-issuer", status_code=302)
        resp.set_cookie(
            cookie_name,
            session.sign_session(user["id"], 0),
            **session.session_cookie_params(request),
        )
        return resp

    @router.get("/debug-oauth")
    def debug_oauth():
        if not DEV_MODE:
            raise HTTPException(status_code=404, detail="Not found")
        cid = os.getenv("GOOGLE_CLIENT_ID", "").strip()
        return {
            "GOOGLE_CLIENT_ID_set": bool(cid),
            "GOOGLE_CLIENT_ID_len": len(cid),
            "env_file_used": _env_path,
            "env_file_exists": os.path.isfile(_env_path),
        }

    @router.get("/terms", response_class=HTMLResponse)
    def terms_page(request: Request):
        return templates.TemplateResponse("terms.html", {"request": request})

    @router.get("/privacy", response_class=HTMLResponse)
    def privacy_page(request: Request):
        return templates.TemplateResponse("privacy.html", {"request": request})

    @router.get("/signup", response_class=HTMLResponse)
    def signup_page(request: Request, error: str | None = Query(None), email: str | None = Query(None), phone: str | None = Query(None), lt: str | None = Query(None)):
        return templates.TemplateResponse(
            "signup.html",
            {
                "request": request,
                "error": _signup_error_message(error),
                "csrf_token": csrf_service.generate_csrf_token(),
                "google_login_url": _google_login_url(request) or "#",
                "facebook_login_url": _facebook_login_url(request) or "#",
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
        from urllib.parse import urlencode, quote
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

    @router.get("/confirmar-perfil", response_class=HTMLResponse)
    def confirmar_perfil_page(request: Request):
        cookie_val = request.cookies.get(cookie_name)
        session_data = session.verify_session(cookie_val)
        if not session_data or session_data[0] == 0:
            return RedirectResponse(url="/login", status_code=302)
        user_id = session_data[0]
        user = users.get_user_by_id(user_id)
        if not user:
            return RedirectResponse(url="/login", status_code=302)
        memberships = users.get_memberships_for_user(user_id)
        if memberships:
            return RedirectResponse(url="/portal/home", status_code=302)
        return templates.TemplateResponse(
            "confirmar_perfil.html",
            {"request": request, "user": user, "error": request.query_params.get("error"), "csrf_token": csrf_service.generate_csrf_token()},
        )

    @router.post("/confirmar-perfil", response_class=RedirectResponse)
    def confirmar_perfil_submit(request: Request, name: str | None = Form(None), csrf_token: str | None = Form(None)):
        token_val = (csrf_token or request.headers.get("X-CSRF-Token") or "").strip()
        if not csrf_service.verify_csrf_token(token_val):
            return RedirectResponse(url="/confirmar-perfil?error=invalid", status_code=302)
        cookie_val = request.cookies.get(cookie_name)
        session_data = session.verify_session(cookie_val)
        if not session_data or session_data[0] == 0:
            return RedirectResponse(url="/login", status_code=302)
        user_id = session_data[0]
        users.update_user_name(user_id, name)
        user = users.get_user_by_id(user_id)
        razon_social = (name or "").strip() or (user.get("email") or "").strip() or "Mi empresa"
        conn = db()
        try:
            cur = conn.execute(
                """INSERT INTO issuers (rfc, razon_social, regimen_fiscal, active)
                   VALUES (?, ?, ?, 1)""",
                ("PENDIENTE", razon_social, None),
            )
            issuer_id = cur.lastrowid
            conn.commit()
        finally:
            conn.close()
        users.add_membership(user_id, issuer_id, "owner")
        resp = RedirectResponse(url="/portal/config/sat", status_code=302)
        resp.set_cookie(
            cookie_name,
            session.sign_session(user_id, issuer_id),
            **session.session_cookie_params(request),
        )
        return resp

    @router.get("/onboarding", response_class=HTMLResponse)
    def onboarding_page(request: Request):
        """Legacy onboarding page — now redirects to SAT config (FIEL upload)."""
        return RedirectResponse(url="/portal/config/sat", status_code=302)

    @router.post("/onboarding", response_class=RedirectResponse)
    def onboarding_submit(
        request: Request,
        rfc: str = Form(...),
        razon_social: str = Form(...),
        regimen_fiscal: str = Form("616"),
        cp: str | None = Form(None),
        authorize_firm: str | None = Form(None),
        csrf_token: str | None = Form(None),
    ):
        token_val = (csrf_token or request.headers.get("X-CSRF-Token") or "").strip()
        if not csrf_service.verify_csrf_token(token_val):
            return RedirectResponse(url="/onboarding?error=invalid", status_code=302)
        cookie_val = request.cookies.get(cookie_name)
        session_data = session.verify_session(cookie_val)
        if not session_data or session_data[0] == 0:
            return RedirectResponse(url="/login", status_code=302)
        user_id, issuer_id = session_data[0], session_data[1]
        rfc = (rfc or "").strip().upper()
        razon_social = (razon_social or "").strip()
        if not rfc or not razon_social:
            return RedirectResponse(url="/onboarding?error=required", status_code=302)
        conn = db()
        try:
            if issuer_id and issuer_id > 0:
                conn.execute(
                    """UPDATE issuers SET rfc = ?, razon_social = ?, regimen_fiscal = ?, updated_at = datetime('now')
                       WHERE id = ?""",
                    (rfc, razon_social, (regimen_fiscal or "").strip() or None, issuer_id),
                )
            else:
                cur = conn.execute(
                    """INSERT INTO issuers (rfc, razon_social, regimen_fiscal, active)
                       VALUES (?, ?, ?, 1)""",
                    (rfc, razon_social, (regimen_fiscal or "").strip() or None),
                )
                issuer_id = cur.lastrowid
                users.add_membership(user_id, issuer_id, "owner")
            if authorize_firm == "on":
                firm_id = users.get_firm_user_id()
                if firm_id:
                    users.add_membership(firm_id, issuer_id, "accountant")
            conn.commit()
        finally:
            conn.close()
        resp = RedirectResponse(url="/portal/home", status_code=302)
        resp.set_cookie(
            cookie_name,
            session.sign_session(user_id, issuer_id),
            **session.session_cookie_params(request),
        )
        return resp

    return router
