"""
Rate limit por IP: ventana deslizante en memoria.

Usado en auth (login, register, forgot, reset) y en portal (FIEL upload, validate, sat_sync).
API: is_rate_limited(request, key_prefix) -> True si se debe bloquear (429/redirect).
"""
import time
from collections import defaultdict
from fastapi import Request

_STORE: dict[str, list[float]] = defaultdict(list)
_DEFAULT_WINDOW = 60.0
_DEFAULT_MAX = 10


def get_client_ip(request: Request) -> str:
    """IP del cliente: X-Forwarded-For, X-Real-IP o request.client.host."""
    raw = request.headers.get("x-forwarded-for") or request.headers.get("x-real-ip")
    if not raw and getattr(request, "client", None):
        raw = getattr(request.client, "host", None)
    return (raw or "").split(",")[0].strip() or "unknown"


def is_rate_limited(
    request: Request,
    key_prefix: str,
    *,
    window_seconds: float = _DEFAULT_WINDOW,
    max_attempts: int = _DEFAULT_MAX,
) -> bool:
    """
    True si la petición debe bloquearse por rate limit (máx. intentos en ventana).
    Si no, registra el intento y devuelve False.
    Clave: key_prefix + ":" + IP.
    """
    ip = get_client_ip(request)
    key = f"{key_prefix}:{ip}"
    now = time.time()
    _STORE[key] = [t for t in _STORE[key] if now - t < window_seconds]
    if len(_STORE[key]) >= max_attempts:
        return True
    _STORE[key].append(now)
    return False
