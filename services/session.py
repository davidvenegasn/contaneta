"""Sesión (cookie) y parámetros de cookie."""
import base64
import hashlib
import hmac
import logging
import time
from typing import Optional

from fastapi import Request

from config import (
    COOKIE_DEMO_VIEW,
    COOKIE_SECURE,
    DEV_MODE,
    SESSION_COOKIE_NAME,
    SESSION_SECRET,
    SESSION_TTL_DAYS,
)
# Cookie: HttpOnly siempre; SameSite=Lax (protege CSRF); Secure en prod o cuando X-Forwarded-Proto=https

logger = logging.getLogger(__name__)


def _log_session_invalid(reason: str) -> None:
    """Log solo en DEV cuando la sesión es inválida (para diagnóstico)."""
    if DEV_MODE:
        logger.debug("session invalid: %s", reason)


def sign_session(user_id: int, issuer_id: int, restore_issuer_id: Optional[int] = None) -> str:
    """Firma payload user_id|issuer_id|expiry[|restore_issuer_id] con HMAC. user_id=0 = sesión legacy."""
    expiry = int(time.time()) + SESSION_TTL_DAYS * 86400
    payload = f"{user_id}|{issuer_id}|{expiry}"
    if restore_issuer_id is not None:
        payload += f"|{restore_issuer_id}"
    sig = hmac.new(SESSION_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(f"{payload}.{sig}".encode()).decode().rstrip("=")


def verify_session(cookie_val: Optional[str]) -> Optional[tuple]:
    """Devuelve (user_id, issuer_id, restore_issuer_id|None). user_id=0 = legacy por token."""
    if not cookie_val or not cookie_val.strip():
        _log_session_invalid("missing cookie")
        return None
    try:
        raw = base64.urlsafe_b64decode(cookie_val + "==")
        s = raw.decode()
    except Exception as e:
        _log_session_invalid("bad decode: %s" % (e,))
        return None
    if "." not in s:
        _log_session_invalid("bad format (no signature)")
        return None
    payload, sig = s.rsplit(".", 1)
    expected = hmac.new(SESSION_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        _log_session_invalid("bad signature")
        return None
    parts = payload.split("|")
    if len(parts) == 2:
        issuer_id, expiry = int(parts[0]), int(parts[1])
        if time.time() > expiry:
            _log_session_invalid("expired (legacy 2-part)")
            return None
        return (0, issuer_id, None)
    if len(parts) == 3:
        user_id, issuer_id, expiry = int(parts[0]), int(parts[1]), int(parts[2])
        if time.time() > expiry:
            _log_session_invalid("expired (3-part)")
            return None
        return (user_id, issuer_id, None)
    if len(parts) == 4:
        user_id, issuer_id, expiry, restore_issuer_id = (
            int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3])
        )
        if time.time() > expiry:
            _log_session_invalid("expired (4-part)")
            return None
        return (user_id, issuer_id, restore_issuer_id)
    _log_session_invalid("bad payload parts")
    return None


def session_cookie_params(request: Optional[Request] = None) -> dict:
    """Cookie segura: HttpOnly, SameSite=Lax. Secure solo si la petición es HTTPS (o x-forwarded-proto=https). En HTTP (localhost) Secure=False para que el navegador guarde la cookie."""
    secure = COOKIE_SECURE
    if request is not None:
        proto = (request.headers.get("x-forwarded-proto") or "").strip().lower()
        scheme = getattr(request.url, "scheme", "") or ""
        if proto == "https" or scheme == "https":
            secure = True
        else:
            secure = False
    return {
        "httponly": True,
        "samesite": "lax",
        "secure": secure,
        "max_age": SESSION_TTL_DAYS * 86400,
        "path": "/",
    }


def get_session_cookie_name() -> str:
    return SESSION_COOKIE_NAME


def get_cookie_demo_view() -> str:
    return COOKIE_DEMO_VIEW
