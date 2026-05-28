"""Auth helpers: cooldown tracking, error message mappers, URL builders."""
import os
import time
from collections import defaultdict
from urllib.parse import quote

from fastapi import Request

# Dummy bcrypt hash for constant-time login (prevents timing-based user enumeration)
DUMMY_HASH = "$2b$12$U6hZVXXPMyR82NvkOKCr2O4o/torbd/ZHVpPFSDM09kGjGX20spOW"

# Cooldown por email: desactivado (no bloquear por intentos fallidos)
_LOGIN_FAILURES_BY_EMAIL: dict[str, list[float]] = defaultdict(list)
_EMAIL_FAILURES_WINDOW = 900.0
_EMAIL_MAX_FAILURES = 5
_EMAIL_COOLDOWN_SECONDS = 900  # 15 minutos
_EMAIL_COOLDOWN_UNTIL: dict[str, float] = {}


def login_email_cooldown(email: str | None) -> bool:
    """True si el email está en cooldown tras 5 fallos de login."""
    if not email or not email.strip():
        return False
    e = (email or "").strip().lower()
    now = time.time()
    if now < _EMAIL_COOLDOWN_UNTIL.get(e, 0):
        return True
    return False


def record_login_failure(email: str | None) -> None:
    """Registra un fallo de login para el email; si llega a 5, activa cooldown."""
    if not email or not email.strip():
        return
    e = (email or "").strip().lower()
    now = time.time()
    _LOGIN_FAILURES_BY_EMAIL[e] = [t for t in _LOGIN_FAILURES_BY_EMAIL[e] if now - t < _EMAIL_FAILURES_WINDOW]
    _LOGIN_FAILURES_BY_EMAIL[e].append(now)
    if len(_LOGIN_FAILURES_BY_EMAIL[e]) >= _EMAIL_MAX_FAILURES:
        _EMAIL_COOLDOWN_UNTIL[e] = now + _EMAIL_COOLDOWN_SECONDS


def clear_login_cooldown(email: str | None) -> None:
    """Clears cooldown state for a successful login."""
    if email:
        _EMAIL_COOLDOWN_UNTIL.pop(email, None)
        _LOGIN_FAILURES_BY_EMAIL.pop(email, None)


def login_error_message(code: str | None) -> str | None:
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


def signup_error_message(code: str | None) -> str | None:
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


def register_error_message(code: str | None) -> str | None:
    msgs = {
        "error": "No se pudo crear la cuenta. Intenta de nuevo.",
        "password": "La contraseña debe tener al menos 8 caracteres.",
        "required": "Completa todos los campos obligatorios.",
    }
    return msgs.get(code or "", None)


def forgot_error_message(code: str | None) -> str | None:
    msgs = {
        "error": "No se pudo enviar el correo. Intenta más tarde.",
        "email": "Indica tu correo electrónico.",
    }
    return msgs.get(code or "", None)


def reset_error_message(code: str | None) -> str | None:
    msgs = {
        "error": "El enlace no es válido o ha expirado. Solicita uno nuevo.",
        "password": "La contraseña debe tener al menos 8 caracteres.",
        "mismatch": "Las contraseñas no coinciden.",
    }
    return msgs.get(code or "", None)


def base_url(request: Request) -> str:
    base = os.getenv("SITE_URL", "").strip()
    if base:
        return base.rstrip("/")
    return str(request.base_url).rstrip("/")


def oauth_redirect_base(request: Request) -> str:
    base = os.getenv("SITE_URL", "").strip()
    if base:
        return base.rstrip("/")
    return str(request.base_url).rstrip("/")


def google_login_url(request: Request) -> str:
    cid = os.getenv("GOOGLE_CLIENT_ID", "").strip()
    if not cid:
        return ""
    base = oauth_redirect_base(request)
    redirect_uri = quote(f"{base}/auth/google/callback", safe="")
    scopes = "openid%20email%20profile%20https://www.googleapis.com/auth/user.phonenumbers.read"
    return f"https://accounts.google.com/o/oauth2/v2/auth?client_id={cid}&redirect_uri={redirect_uri}&response_type=code&scope={scopes}"


def facebook_login_url(request: Request) -> str:
    app_id = os.getenv("FACEBOOK_APP_ID", "").strip()
    if not app_id:
        return ""
    base = oauth_redirect_base(request)
    redirect_uri = quote(f"{base}/auth/facebook/callback", safe="")
    return f"https://www.facebook.com/v18.0/dialog/oauth?client_id={app_id}&redirect_uri={redirect_uri}&scope=email,public_profile"
