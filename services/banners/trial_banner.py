"""Compute trial expiry banner state for an issuer."""

import logging
from datetime import datetime, timedelta
from typing import Optional

from database import db

logger = logging.getLogger(__name__)


def compute_trial_banner_state(issuer_id: int) -> Optional[dict]:
    """Return banner dict if issuer is on an active trial, else None.

    Args:
        issuer_id: Tenant ID.

    Returns:
        Banner dict with keys: key, visible, variant, title, message, cta_url, cta_label, dismissable.
        None if no banner needed.
    """
    if not issuer_id or issuer_id <= 0:
        return None

    conn = db()
    try:
        row = conn.execute(
            "SELECT trial_expires_at FROM issuers WHERE id = ? LIMIT 1",
            (issuer_id,),
        ).fetchone()
    finally:
        conn.close()

    if not row or not row.get("trial_expires_at"):
        return None

    try:
        expires = datetime.fromisoformat(row["trial_expires_at"].replace("Z", "+00:00").replace("+00:00", ""))
    except (ValueError, AttributeError):
        return None

    now = datetime.now()
    days_left = (expires - now).days

    if days_left < 0:
        # Trial expired
        return {
            "key": "trial_expired",
            "visible": True,
            "variant": "danger",
            "title": "Tu periodo de prueba terminó",
            "message": "Suscríbete para seguir emitiendo facturas y sincronizando con el SAT.",
            "cta_url": "/pricing",
            "cta_label": "Ver planes",
            "dismissable": False,
        }
    elif days_left <= 3:
        return {
            "key": "trial_expiring_soon",
            "visible": True,
            "variant": "danger",
            "title": f"Tu prueba vence en {days_left + 1} día{'s' if days_left > 0 else ''}",
            "message": "Suscríbete ahora para no perder acceso.",
            "cta_url": "/pricing",
            "cta_label": "Ver planes",
            "dismissable": False,
        }
    elif days_left <= 7:
        return {
            "key": "trial_expiring",
            "visible": True,
            "variant": "warn",
            "title": f"Tu prueba vence en {days_left + 1} días",
            "message": "Explora todos los planes disponibles.",
            "cta_url": "/pricing",
            "cta_label": "Ver planes",
            "dismissable": True,
        }

    return None
