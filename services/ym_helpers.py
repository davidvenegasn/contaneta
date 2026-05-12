"""Centralized year-month helpers for annual vs monthly view."""

import re

MESES_ES = (
    "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
    "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
)

_RE_YYYY = re.compile(r"^\d{4}$")
_RE_YYYY_MM = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def is_annual(ym: str) -> bool:
    """True if ym is year-only (4 digits), e.g. '2026'."""
    return bool(ym and _RE_YYYY.match(ym.strip()))


def validate_ym(ym: str) -> str:
    """Validate and normalize ym. Returns clean YYYY or YYYY-MM, raises ValueError on bad input."""
    s = (ym or "").strip()
    if _RE_YYYY_MM.match(s):
        return s
    if _RE_YYYY.match(s):
        return s
    raise ValueError(f"Invalid ym format: {ym!r}")


def ym_sql_filter(ym: str) -> str:
    """Return SQL WHERE fragment: substr(fecha_emision,1,4) = ? for annual, substr(fecha_emision,1,7) = ? for monthly."""
    if is_annual(ym):
        return "substr(fecha_emision,1,4) = ?"
    return "substr(fecha_emision,1,7) = ?"


def ym_sql_len(ym: str) -> int:
    """Return the substr length for the given ym format (4 or 7)."""
    return 4 if is_annual(ym) else 7


def ym_to_label(ym: str) -> str:
    """Convert '2026-01' to 'Enero 2026', '2026' to '2026'."""
    s = (ym or "").strip()
    if is_annual(s):
        return s
    try:
        y, m = s.split("-")
        return f"{MESES_ES[int(m) - 1]} {y}"
    except (ValueError, IndexError):
        return s


def shift_ym(ym: str, delta: int) -> str:
    """Shift ym by delta months (monthly) or delta years (annual)."""
    s = (ym or "").strip()
    if is_annual(s):
        return str(int(s) + delta)
    y, m = s.split("-")
    y, m = int(y), int(m)
    m += delta
    while m <= 0:
        m += 12
        y -= 1
    while m >= 13:
        m -= 12
        y += 1
    return f"{y:04d}-{m:02d}"


def sanitize_ym(raw: str, fallback: str) -> str:
    """Sanitize raw ym input: accept YYYY or YYYY-MM, return fallback on bad input."""
    s = (raw or "").strip()
    if _RE_YYYY_MM.match(s) or _RE_YYYY.match(s):
        return s
    return fallback
