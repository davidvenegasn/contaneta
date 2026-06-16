"""Compute usage limit banner state for an issuer."""

import logging
from typing import Optional

from database import db

logger = logging.getLogger(__name__)


def compute_usage_banner_state(issuer_id: int) -> Optional[dict]:
    """Return banner dict if issuer is near/at plan usage limit, else None.

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
            """SELECT plan_invoice_limit, plan_invoices_used
               FROM issuers WHERE id = ? LIMIT 1""",
            (issuer_id,),
        ).fetchone()
    except Exception:
        return None
    finally:
        conn.close()

    if not row:
        return None

    limit = row.get("plan_invoice_limit") or 0
    used = row.get("plan_invoices_used") or 0

    if not limit or limit <= 0:
        return None  # unlimited or no limit set

    pct = (used / limit) * 100

    if pct >= 100:
        return {
            "key": "usage_limit_reached",
            "visible": True,
            "variant": "danger",
            "title": "Límite de facturas alcanzado",
            "message": f"Has emitido {used}/{limit} facturas de tu plan. Actualiza tu plan para seguir facturando.",
            "cta_url": "/pricing",
            "cta_label": "Actualizar plan",
            "dismissable": False,
        }
    elif pct >= 80:
        return {
            "key": "usage_limit_warning",
            "visible": True,
            "variant": "warn",
            "title": f"Llevas {used} de {limit} facturas",
            "message": "Estás cerca del límite de tu plan.",
            "cta_url": "/pricing",
            "cta_label": "Ver planes",
            "dismissable": True,
        }

    return None
