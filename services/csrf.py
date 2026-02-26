"""Token CSRF firmado para POSTs sensibles (login, register, submit) y mutaciones /api/*."""
import hmac
import hashlib
import time
import secrets
import base64

from fastapi import Request
from config import SESSION_SECRET

CSRF_MAX_AGE_SECONDS = 3600  # 1 hora


def _sign(payload: str) -> str:
    return hmac.new(SESSION_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()


def generate_csrf_token() -> str:
    """Genera un token CSRF firmado (timestamp:nonce). Válido CSRF_MAX_AGE_SECONDS."""
    ts = int(time.time())
    nonce = secrets.token_hex(8)
    payload = f"{ts}:{nonce}"
    sig = _sign(payload)
    raw = f"{payload}.{sig}"
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def verify_csrf_token(token: str | None, max_age_seconds: int | None = None) -> bool:
    """Verifica que el token sea válido y no haya expirado. max_age_seconds=None usa CSRF_MAX_AGE_SECONDS."""
    if not token or not token.strip():
        return False
    # Por si el form convierte + en espacio (application/x-www-form-urlencoded)
    token_clean = token.strip().replace(" ", "+")
    max_age = max_age_seconds if max_age_seconds is not None else CSRF_MAX_AGE_SECONDS
    try:
        raw = base64.urlsafe_b64decode(token_clean + "==")
        s = raw.decode()
    except Exception:
        return False
    if "." not in s:
        return False
    payload, sig = s.rsplit(".", 1)
    if not hmac.compare_digest(_sign(payload), sig):
        return False
    parts = payload.split(":")
    if len(parts) != 2:
        return False
    ts = int(parts[0])
    if time.time() - ts > max_age:
        return False
    return True


def verify_api_csrf(request: Request) -> None:
    """
    Exige header X-CSRF-Token válido para mutaciones /api/* con auth por cookie.
    Si falta o es inválido, lanza HTTPException 403 (JSON).
    """
    from fastapi import HTTPException

    token = (request.headers.get("X-CSRF-Token") or "").strip()
    if not verify_csrf_token(token):
        raise HTTPException(status_code=403, detail="Invalid or missing CSRF token")
