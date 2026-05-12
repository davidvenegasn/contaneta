"""
Motor de matching Movimientos ↔ CFDI (fase 1, sin IA).

Nota: el matching productivo actual vive en `services/bank_cfdi_matching.py`.
Este módulo expone una interfaz más genérica para futuros usos (p. ej. sugerencias desde listas CFDI).
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from database import db, table_exists
from services.bank.bank_cfdi_matching import score_movement_cfdi

logger = logging.getLogger(__name__)


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


def score_label(score: int) -> str:
    """Human-readable label for a match score."""
    if score >= 90:
        return "muy_probable"
    elif score >= 70:
        return "probable"
    elif score >= 50:
        return "revisar"
    return "sin_match"


def preview_month(issuer_id: int, ym: str) -> dict[str, Any]:
    """
    Preview matching for a whole month. Returns summary + per-movement best match.
    Does NOT persist suggestions — use refresh_suggestions_for_month for that.
    """
    issuer_id = int(issuer_id)
    ym = (ym or "").strip()[:7]
    if not ym:
        from datetime import datetime
        ym = datetime.now().strftime("%Y-%m")

    conn = db()
    try:
        if not table_exists(conn, "bank_movements"):
            return {"movements": 0, "matched": 0, "summary": {}}

        # Count movements by match status
        has_bim = table_exists(conn, "bank_invoice_matches")
        summary = {"muy_probable": 0, "probable": 0, "revisar": 0, "sin_match": 0}

        movs = conn.execute(
            "SELECT id, deposito, retiro, fecha FROM bank_movements WHERE issuer_id = ? AND period_month = ?",
            (issuer_id, ym),
        ).fetchall()

        total = len(movs)
        matched = 0

        if has_bim:
            for m in movs:
                mid = m["id"]
                best = conn.execute(
                    """SELECT MAX(score) AS best_score FROM bank_invoice_matches
                       WHERE issuer_id = ? AND bank_movement_id = ? AND status IN ('suggested','confirmed')""",
                    (issuer_id, mid),
                ).fetchone()
                best_score = int(best["best_score"] or 0) if best and best["best_score"] else 0
                label = score_label(best_score)
                summary[label] = summary.get(label, 0) + 1
                if best_score >= 50:
                    matched += 1
        else:
            summary["sin_match"] = total

        return {
            "ym": ym,
            "movements": total,
            "matched": matched,
            "unmatched": total - matched,
            "summary": summary,
        }
    finally:
        conn.close()

