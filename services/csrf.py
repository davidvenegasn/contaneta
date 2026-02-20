"""Token CSRF firmado para POSTs sensibles (login, register, submit)."""
import hmac
import hashlib
import time
import secrets
import base64

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


def verify_csrf_token(token: str | None) -> bool:
    """Verifica que el token sea válido y no haya expirado."""
    if not token or not token.strip():
        return False
    try:
        raw = base64.urlsafe_b64decode(token.strip() + "==")
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
    if time.time() - ts > CSRF_MAX_AGE_SECONDS:
        return False
    return True
