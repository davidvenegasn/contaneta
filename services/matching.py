"""
Motor de matching Movimientos ↔ CFDI (fase 1, sin IA).

Nota: el matching productivo actual vive en `services/bank_cfdi_matching.py`.
Este módulo expone una interfaz más genérica para futuros usos (p. ej. sugerencias desde listas CFDI).
"""

from __future__ import annotations

from typing import Any, Optional

from services.bank_cfdi_matching import score_movement_cfdi


def match_by_amount_date_counterparty(
    movement: dict[str, Any],
    cfdi: dict[str, Any],
    *,
    issuer_rfc: Optional[str] = None,
) -> dict[str, Any]:
    """
    Returns:
      { score: 0-100, reasons: [..], breakdown: {...} }
    """
    score, breakdown = score_movement_cfdi(movement, cfdi, issuer_rfc=issuer_rfc)
    reasons: list[str] = []
    notes = breakdown.get("notes") if isinstance(breakdown, dict) else None
    if isinstance(notes, list):
        for n in notes[:8]:
            if n and isinstance(n, str):
                reasons.append(n)
    if score >= 90:
        reasons.insert(0, "Match muy probable")
    elif score >= 70:
        reasons.insert(0, "Match probable")
    elif score >= 50:
        reasons.insert(0, "Match posible")
    else:
        reasons.insert(0, "Match débil")
    return {"score": int(score), "reasons": reasons, "breakdown": breakdown}

