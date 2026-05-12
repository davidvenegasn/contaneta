"""Sesion (cookie) y parametros de cookie."""
import base64
import hashlib
import hmac
import logging
import secrets
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
    """Log solo en DEV cuando la sesion es invalida (para diagnostico)."""
    if DEV_MODE:
        logger.debug("session invalid: %s", reason)


def _hmac_key_for_user(user_id: int) -> bytes:
    """Derive the HMAC signing key for a user.

    For user_id > 0, incorporates the user's session_nonce so that
    rotating the nonce (e.g. on password change) cryptographically
    invalidates all existing sessions.  Falls back to the global
    SESSION_SECRET when no nonce exists or for legacy (user_id=0)
    sessions.
    """
    base_key = SESSION_SECRET
    if user_id and user_id > 0:
        try:
            from database import db as _db, db_rows, has_column
            conn = _db()
            try:
                has_nonce = has_column(conn, "users", "session_nonce")
            finally:
                conn.close()
            if has_nonce:
                rows = db_rows(
                    "SELECT session_nonce FROM users WHERE id = ? LIMIT 1",
                    (user_id,),
                )
                nonce = (rows[0].get("session_nonce") or "") if rows else ""
                if nonce:
                    base_key = f"{SESSION_SECRET}:{nonce}"
        except Exception:
            # Fallback to global secret on any DB error (e.g. during tests)
            pass
    return base_key.encode()


def generate_session_nonce() -> str:
    """Generate a new random session nonce (16 hex chars)."""
    return secrets.token_hex(8)


def sign_session(user_id: int, issuer_id: int, restore_issuer_id: Optional[int] = None) -> str:
    """Firma payload user_id|issuer_id|expiry[|restore_issuer_id] con HMAC. user_id=0 = sesion legacy."""
    expiry = int(time.time()) + SESSION_TTL_DAYS * 86400
    payload = f"{user_id}|{issuer_id}|{expiry}"
    if restore_issuer_id is not None:
        payload += f"|{restore_issuer_id}"
    key = _hmac_key_for_user(user_id)
    sig = hmac.new(key, payload.encode(), hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(f"{payload}.{sig}".encode()).decode().rstrip("=")


def verify_session(cookie_val: Optional[str], *, include_expiry: bool = False) -> Optional[tuple]:
    """Devuelve (user_id, issuer_id, restore_issuer_id|None[, expiry]). user_id=0 = legacy por token."""
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
    parts = payload.split("|")

    # Extract user_id from payload to derive the correct HMAC key
    # (incorporates the user's session_nonce when available).
    user_id_for_key = 0
    if len(parts) >= 3:
        try:
            user_id_for_key = int(parts[0])
        except (ValueError, IndexError):
            user_id_for_key = 0

    key = _hmac_key_for_user(user_id_for_key)
    expected = hmac.new(key, payload.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        # Fallback: try the global key for backward compatibility with sessions
        # created before the nonce was introduced (signed with SESSION_SECRET only).
        if user_id_for_key > 0:
            fallback = hmac.new(
                SESSION_SECRET.encode(), payload.encode(), hashlib.sha256
            ).hexdigest()
            if not hmac.compare_digest(fallback, sig):
                _log_session_invalid("bad signature")
                return None
            # Signature matched with the global key -- pre-nonce session.
            # The password_changed_at check in deps.py still applies.
        else:
            _log_session_invalid("bad signature")
            return None

    if len(parts) == 2:
        issuer_id, expiry = int(parts[0]), int(parts[1])
        if time.time() > expiry:
            _log_session_invalid("expired (legacy 2-part)")
            return None
        base = (0, issuer_id, None)
        return (*base, expiry) if include_expiry else base
    if len(parts) == 3:
        user_id, issuer_id, expiry = int(parts[0]), int(parts[1]), int(parts[2])
        if time.time() > expiry:
            _log_session_invalid("expired (3-part)")
            return None
        base = (user_id, issuer_id, None)
        return (*base, expiry) if include_expiry else base
    if len(parts) == 4:
        user_id, issuer_id, expiry, restore_issuer_id = (
            int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3])
        )
        if time.time() > expiry:
            _log_session_invalid("expired (4-part)")
            return None
        base = (user_id, issuer_id, restore_issuer_id)
        return (*base, expiry) if include_expiry else base
    _log_session_invalid("bad payload parts")
    return None


def session_cookie_params(request: Optional[Request] = None) -> dict[str, object]:
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
