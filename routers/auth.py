"""Rutas de autenticación: login, signup, OAuth, confirmar perfil, onboarding, register."""
import logging
import os
import time
from collections import defaultdict
from urllib.parse import quote

from fastapi import APIRouter, Request, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse
import httpx

from config import _env_path
from database import db
from services import issuers, session, users, audit, csrf as csrf_service
from services import sanitize as sanitize_service

logger = logging.getLogger(__name__)

# Rate-limit login: por IP, máx 5 intentos por ventana de 60 s
_LOGIN_ATTEMPTS: dict[str, list[float]] = defaultdict(list)
_LOGIN_WINDOW = 60.0
_LOGIN_MAX_ATTEMPTS = 5

# Rate-limit registro: por IP, máx 3 intentos por ventana de 60 s
_REGISTER_ATTEMPTS: dict[str, list[float]] = defaultdict(list)
_REGISTER_WINDOW = 60.0
_REGISTER_MAX_ATTEMPTS = 3


def _client_ip(request: Request) -> str:
    return (request.headers.get("x-forwarded-for") or request.headers.get("x-real-ip") or request.client.host or "").split(",")[0].strip() or "unknown"


def _login_rate_limit(request: Request) -> bool:
    """True si se debe bloquear (rate limit excedido). Si no, registra intento y devuelve False."""
    ip = _client_ip(request)
    now = time.time()
    _LOGIN_ATTEMPTS[ip] = [t for t in _LOGIN_ATTEMPTS[ip] if now - t < _LOGIN_WINDOW]
    if len(_LOGIN_ATTEMPTS[ip]) >= _LOGIN_MAX_ATTEMPTS:
        return True
    _LOGIN_ATTEMPTS[ip].append(now)
    return False


def _register_rate_limit(request: Request) -> bool:
    """True si se debe bloquear registro por IP (rate limit excedido)."""
    ip = _client_ip(request)
    now = time.time()
    _REGISTER_ATTEMPTS[ip] = [t for t in _REGISTER_ATTEMPTS[ip] if now - t < _REGISTER_WINDOW]
    if len(_REGISTER_ATTEMPTS[ip]) >= _REGISTER_MAX_ATTEMPTS:
        return True
    _REGISTER_ATTEMPTS[ip].append(now)
    return False


def _login_error_message(code: str | None) -> str | None:
    # Mensajes genéricos: no revelar "email existe" / "email no existe"
    msgs = {
        "invalid": "Datos inválidos. Intenta de nuevo.",
        "email_or_phone": "Datos inválidos. Intenta de nuevo.",
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
        "email_exists": "No se pudo crear la cuenta. Intenta de nuevo.",
        "phone_exists": "No se pudo crear la cuenta. Intenta de nuevo.",
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

    def _render_login(request: Request, error: str | None = None):
        return templates.TemplateResponse(
            "login.html",
            {
                "request": request,
                "error": error,
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
    ):
        if not csrf_service.verify_csrf_token(csrf_token):
            return RedirectResponse(url="/login?error=invalid", status_code=302)
        if _login_rate_limit(request):
            time.sleep(2)
            return RedirectResponse(url="/login?error=invalid", status_code=302)
        if login_type != "credentials" or not password:
            return RedirectResponse(url="/login?error=invalid", status_code=302)
        email = (email or "").strip().lower() or None
        phone = (phone or "").strip() or None
        if cred_type == "phone":
            email = None
        else:
            phone = None
        if not email and not phone:
            return RedirectResponse(url="/login?error=email_or_phone", status_code=302)
        user = users.get_user_by_email_or_phone(email or phone)
        if not user:
            return RedirectResponse(url="/login?error=bad_credentials", status_code=302)
        hashed = users.get_user_password_hash(user["id"])
        if not hashed or not users.verify_password(password, hashed):
            return RedirectResponse(url="/login?error=bad_credentials", status_code=302)
        memberships = users.get_memberships_for_user(user["id"])
        if not memberships:
            audit.log(action="login", user_id=user["id"], issuer_id=0, details="credentials")
            resp = RedirectResponse(url="/confirmar-perfil", status_code=302)
            resp.set_cookie(
                cookie_name,
                session.sign_session(user["id"], 0),
                **session.session_cookie_params(request),
            )
            return resp
        if len(memberships) == 1:
            issuer_id = memberships[0]["issuer_id"]
            audit.log(action="login", user_id=user["id"], issuer_id=issuer_id, details="credentials")
            resp = RedirectResponse(url="/portal/home", status_code=302)
            resp.set_cookie(
                cookie_name,
                session.sign_session(user["id"], issuer_id),
                **session.session_cookie_params(request),
            )
            return resp
        audit.log(action="login", user_id=user["id"], issuer_id=0, details="credentials")
        resp = RedirectResponse(url="/choose-issuer", status_code=302)
        resp.set_cookie(
            cookie_name,
            session.sign_session(user["id"], 0),
            **session.session_cookie_params(request),
        )
        return resp

    @router.get("/register", response_class=HTMLResponse)
    def register_page(request: Request, error: str | None = Query(None)):
        return templates.TemplateResponse(
            "register.html",
            {"request": request, "error": _register_error_message(error), "csrf_token": csrf_service.generate_csrf_token()},
        )

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
        if not csrf_service.verify_csrf_token(csrf_token):
            return RedirectResponse(url="/register?error=error", status_code=302)
        if _register_rate_limit(request):
            time.sleep(2)
            return RedirectResponse(url="/register?error=error", status_code=302)
        email = sanitize_service.sanitize_email(email)
        if not email:
            return RedirectResponse(url="/register?error=required", status_code=302)
        if not password or len(password) < 8:
            return RedirectResponse(url="/register?error=password", status_code=302)
        rfc = sanitize_service.sanitize_rfc(rfc)
        razon_social = (razon_social or "").strip()[:200]
        if not rfc or not razon_social:
            return RedirectResponse(url="/register?error=required", status_code=302)
        cp = sanitize_service.sanitize_cp(cp)
        if cp is not None and len(cp) != 5:
            cp = None
        if users.get_user_by_email(email):
            return RedirectResponse(url="/register?error=error", status_code=302)
        try:
            user = users.create_user(
                email=email,
                password_hash=users.hash_password(password),
                name=razon_social,
            )
        except Exception as e:
            logger.exception("Register create_user: %s", e)
            return RedirectResponse(url="/register?error=error", status_code=302)
        try:
            issuer_id, _ = issuers.create_issuer_with_token(
                rfc=rfc,
                razon_social=razon_social,
                regimen_fiscal=(regimen_fiscal or "").strip() or None,
            )
            users.add_membership(user["id"], issuer_id, "owner")
        except Exception as e:
            logger.exception("Register create_issuer/membership: %s", e)
            return RedirectResponse(url="/register?error=error", status_code=302)
        audit.log(
            action="register",
            user_id=user["id"],
            issuer_id=issuer_id,
            details=f"email={email[:50]} rfc={rfc}",
        )
        resp = RedirectResponse(url="/portal/home", status_code=302)
        resp.set_cookie(
            cookie_name,
            session.sign_session(user["id"], issuer_id),
            **session.session_cookie_params(request),
        )
        return resp

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
        if not csrf_service.verify_csrf_token(csrf_token):
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
            audit.log(
                action="logout",
                user_id=session_data[0] if session_data[0] else None,
                issuer_id=session_data[1] if session_data[1] else None,
                details="",
            )
        resp = RedirectResponse(url="/", status_code=302)
        resp.delete_cookie(cookie_name, path="/")
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
            logger.warning("Google token exchange failed: %s", token_res.text)
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
            logger.warning("Facebook token exchange failed: %s", token_res.text)
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
    def signup_page(request: Request, error: str | None = Query(None)):
        return templates.TemplateResponse(
            "signup.html",
            {
                "request": request,
                "error": _signup_error_message(error),
                "google_login_url": _google_login_url(request) or "#",
                "facebook_login_url": _facebook_login_url(request) or "#",
                "google_oauth_configured": bool(os.getenv("GOOGLE_CLIENT_ID", "").strip()),
                "facebook_oauth_configured": bool(os.getenv("FACEBOOK_APP_ID", "").strip()),
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
    ):
        if accept_terms != "on":
            return RedirectResponse(url="/signup?error=terms", status_code=302)
        email = (email or "").strip().lower() or None
        phone = (phone or "").strip() or None
        if login_type == "phone":
            email = None
        else:
            phone = None
        if not email and not phone:
            return RedirectResponse(url="/signup?error=email_or_phone", status_code=302)
        if not password or len(password) < 8:
            return RedirectResponse(url="/signup?error=password", status_code=302)
        if password != password_confirm:
            return RedirectResponse(url="/signup?error=password_mismatch", status_code=302)
        if email and users.get_user_by_email(email):
            return RedirectResponse(url="/signup?error=email_exists", status_code=302)
        if phone and users.get_user_by_phone(phone):
            return RedirectResponse(url="/signup?error=phone_exists", status_code=302)
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
            {"request": request, "user": user, "error": request.query_params.get("error")},
        )

    @router.post("/confirmar-perfil", response_class=RedirectResponse)
    def confirmar_perfil_submit(request: Request, name: str | None = Form(None)):
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
        resp = RedirectResponse(url="/portal/home", status_code=302)
        resp.set_cookie(
            cookie_name,
            session.sign_session(user_id, issuer_id),
            **session.session_cookie_params(request),
        )
        return resp

    @router.get("/onboarding", response_class=HTMLResponse)
    def onboarding_page(request: Request):
        cookie_val = request.cookies.get(cookie_name)
        session_data = session.verify_session(cookie_val)
        if not session_data or session_data[0] == 0:
            return RedirectResponse(url="/login", status_code=302)
        user_id, issuer_id = session_data[0], session_data[1]
        if not issuer_id or issuer_id == 0:
            memberships = users.get_memberships_for_user(user_id)
            if not memberships:
                return RedirectResponse(url="/confirmar-perfil", status_code=302)
            issuer_id = memberships[0]["issuer_id"]
        issuer = issuers.get_issuer_by_id(issuer_id)
        if not issuer:
            return RedirectResponse(url="/confirmar-perfil", status_code=302)
        return templates.TemplateResponse(
            "onboarding.html",
            {"request": request, "error": request.query_params.get("error"), "issuer": issuer},
        )

    @router.post("/onboarding", response_class=RedirectResponse)
    def onboarding_submit(
        request: Request,
        rfc: str = Form(...),
        razon_social: str = Form(...),
        regimen_fiscal: str = Form("616"),
        cp: str | None = Form(None),
        authorize_firm: str | None = Form(None),
    ):
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
