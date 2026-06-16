"""Compute onboarding banner state for an issuer."""

import logging
from typing import Optional

from database import db

logger = logging.getLogger(__name__)

MAX_ONBOARDING_STEP = 5


def compute_onboarding_banner_state(issuer_id: int) -> Optional[dict]:
    """Return banner dict if issuer has incomplete onboarding, else None.

    Args:
        issuer_id: Tenant ID.

    Returns:
        Banner dict or None.
    """
    if not issuer_id or issuer_id <= 0:
        return None

    conn = db()
    try:
        row = conn.execute(
            "SELECT onboarding_step, onboarding_dismissed FROM issuers WHERE id = ? LIMIT 1",
            (issuer_id,),
        ).fetchone()
    except Exception:
        return None
    finally:
        conn.close()

    if not row:
        return None

    step = row.get("onboarding_step") or 0
    dismissed = row.get("onboarding_dismissed") or 0

    if dismissed or step >= MAX_ONBOARDING_STEP:
        return None

    return {
        "key": "onboarding_incomplete",
        "visible": True,
        "variant": "info",
        "title": "Completa tu configuración",
        "message": f"Paso {step + 1} de {MAX_ONBOARDING_STEP} — termina de configurar tu cuenta para facturar.",
        "cta_url": "/portal/onboarding",
        "cta_label": "Continuar",
        "dismissable": True,
    }
