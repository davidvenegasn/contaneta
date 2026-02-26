"""
Helpers para no loguear valores sensibles en claro (tokens, email, RFC).
Usar en routers y servicios donde se registren datos de peticiones o usuarios.
"""
from typing import Optional


def mask_token(value: Optional[str], visible: int = 4) -> str:
    """Muestra solo los primeros y últimos visible caracteres. Ej: 'abcd....wxyz'."""
    if not value or not isinstance(value, str):
        return "***"
    v = value.strip()
    if len(v) <= visible * 2:
        return "***"
    return v[:visible] + "...." + v[-visible:]


def mask_email(value: Optional[str]) -> str:
    """Oculta parte del email: 'a***@b.com'."""
    if not value or not isinstance(value, str):
        return "***"
    v = value.strip()
    if "@" not in v:
        return "***"
    local, _, domain = v.partition("@")
    if len(local) <= 2:
        return "***@" + domain
    return local[0] + "***@" + domain


def mask_rfc(value: Optional[str], visible: int = 4) -> str:
    """Oculta parte del RFC para logs. Ej: 'XAXX***123.'."""
    if not value or not isinstance(value, str):
        return "***"
    v = value.strip().upper()
    if len(v) <= visible:
        return "***"
    return v[:visible] + "***" + (v[-3:] if len(v) >= 3 else "")
