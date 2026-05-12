"""Shared helpers for API route modules."""
import json
import logging
import os

from fastapi import HTTPException, Request

from config import BASE_DIR, DEV_FIXTURES
from services.auth.rate_limit import is_rate_limited
from services.sat.sat_sync import get_month_totals as _get_month_totals_raw

logger = logging.getLogger(__name__)

QUOTATION_STATUSES = ("draft", "sent", "accepted", "rejected", "converted", "expired")

# Paginación: nunca devolver miles de filas; siempre limit/offset con tope
DEFAULT_LIST_LIMIT = 200
MAX_LIST_LIMIT = 500
MAX_LIST_OFFSET = 50_000


def _api_rate_check(request: Request, key: str, *, max_attempts: int = 10, window: float = 60.0):
    """Raise 429 if rate limited."""
    if is_rate_limited(request, key, max_attempts=max_attempts, window_seconds=window):
        raise HTTPException(status_code=429, detail="Demasiadas solicitudes. Intenta en un momento.")


def _load_fixture(name: str):
    """Si DEV_FIXTURES está activo, carga JSON desde tests/manual_fixtures/{name}.json."""
    if not DEV_FIXTURES:
        return None
    path = os.path.join(BASE_DIR, "tests", "manual_fixtures", f"{name}.json")
    try:
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        logger.debug("Fixture %s: %s", name, e)
    return None


def _get_month_totals_safe(issuer_id, ym, direction):
    """Wrapper that never raises — returns zeros on error."""
    try:
        return _get_month_totals_raw(issuer_id, ym, direction)
    except Exception:
        return {"total_base": 0, "total_iva": 0, "total_retenciones": 0, "total_iva_neto": 0}
