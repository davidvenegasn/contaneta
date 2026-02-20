"""Sanitización de inputs (email, RFC, CP, montos) para reducir riesgos."""
import re
from typing import Optional


def sanitize_email(value: Optional[str], max_len: int = 254) -> Optional[str]:
    """Lower, strip, limita longitud. No valida formato completo."""
    if value is None:
        return None
    s = (value or "").strip().lower()
    if not s or "@" not in s:
        return None
    return s[:max_len] if len(s) > max_len else s


def sanitize_rfc(value: Optional[str], max_len: int = 13) -> Optional[str]:
    """Solo mayúsculas y caracteres alfanuméricos. Típico RFC 12-13 caracteres."""
    if value is None:
        return None
    s = (value or "").strip().upper()
    s = re.sub(r"[^A-Z0-9]", "", s)
    return s[:max_len] if s else None


def sanitize_cp(value: Optional[str], length: int = 5) -> Optional[str]:
    """Solo dígitos; longitud fija para México (5)."""
    if value is None:
        return None
    s = re.sub(r"\D", "", (value or "").strip())
    if len(s) != length and len(s) > 0:
        s = s[:length]
    return s if s else None


def sanitize_amount(value: Optional[str] | float) -> Optional[float]:
    """Convierte a float no negativo. Acepta string con decimales."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return max(0.0, float(value)) if value >= 0 else None
    s = (value or "").strip().replace(",", ".")
    try:
        n = float(s)
        return max(0.0, n) if n >= 0 else None
    except ValueError:
        return None
