"""
Matching movimiento bancario ↔ CFDI (Fase 5). Scoring y persistencia en bank_invoice_matches.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Any, Optional

from database import db, db_rows, table_exists

logger = logging.getLogger(__name__)

MIN_SCORE_THRESHOLD = 50
MATCH_ROLE_PAYMENT = "payment"
MATCH_ROLE_INCOME = "income"
STATUS_SUGGESTED = "suggested"
STATUS_CONFIRMED = "confirmed"
STATUS_REJECTED = "rejected"


def _parse_date(s: Optional[str]) -> Optional[datetime]:
    """Interpreta fecha YYYY-MM-DD o DD/MM/YYYY."""
    if not s or not isinstance(s, str):
        return None
    s = s.strip()[:10]
    if not s:
        return None
    try:
        if re.match(r"\d{4}-\d{2}-\d{2}", s):
            return datetime.strptime(s, "%Y-%m-%d")
        if re.match(r"\d{2}/\d{2}/\d{4}", s):
            return datetime.strptime(s, "%d/%m/%Y")
        if re.match(r"\d{2}/\d{2}/\d{2}", s):
            return datetime.strptime(s, "%d/%m/%y")
    except Exception:
        pass
    return None


def score_movement_cfdi(
    movement: dict[str, Any],
    cfdi: dict[str, Any],
    issuer_rfc: Optional[str] = None,
) -> tuple[int, dict[str, Any]]:
    """
    Calcula puntaje de coincidencia movimiento ↔ CFDI (0-100).
    movement: fila bank_movements (deposito, retiro, fecha, descripcion, rfc_encontrado, counterparty_rfc_detected).
    cfdi: fila sat_cfdi (total, fecha_emision, rfc_emisor, rfc_receptor, uuid).
    Returns (score, breakdown_dict).
    """
    breakdown: dict[str, Any] = {"amount": 0, "date": 0, "rfc": 0, "notes": []}
    movement_amount = float(movement.get("deposito") or movement.get("retiro") or movement.get("amount") or 0)
    cfdi_total = float(cfdi.get("total") or 0)
    if movement_amount <= 0 or cfdi_total <= 0:
        breakdown["notes"].append("Monto inválido")
        return 0, breakdown
    amount_ratio = min(movement_amount, cfdi_total) / max(movement_amount, cfdi_total)
    if amount_ratio >= 0.995:
        breakdown["amount"] = 40
    elif amount_ratio >= 0.95:
        breakdown["amount"] = 30
    elif amount_ratio >= 0.90:
        breakdown["amount"] = 20
    else:
        breakdown["notes"].append("Diferencia de monto >10%")
        breakdown["amount"] = max(0, int(20 * amount_ratio))

    mov_date = _parse_date(movement.get("fecha"))
    cfdi_date = _parse_date(cfdi.get("fecha_emision"))
    if mov_date and cfdi_date:
        delta = abs((mov_date - cfdi_date).days)
        if delta <= 3:
            breakdown["date"] = 40
        elif delta <= 7:
            breakdown["date"] = 30
        elif delta <= 31:
            breakdown["date"] = 15
        else:
            breakdown["date"] = max(0, 15 - delta // 30)
    else:
        breakdown["date"] = 10
        breakdown["notes"].append("Fecha no parseable")

    mov_rfc = (movement.get("rfc_encontrado") or movement.get("counterparty_rfc_detected") or "").strip().upper()
    cfdi_emisor = (cfdi.get("rfc_emisor") or "").strip().upper()
    cfdi_receptor = (cfdi.get("rfc_receptor") or "").strip().upper()
    issuer = (issuer_rfc or "").strip().upper()
    rfc_match = False
    if mov_rfc and (mov_rfc == cfdi_emisor or mov_rfc == cfdi_receptor):
        rfc_match = True
    if issuer and (issuer == cfdi_emisor or issuer == cfdi_receptor):
        if movement_amount and cfdi_total and abs(movement_amount - cfdi_total) < 1.0:
            rfc_match = True
    breakdown["rfc"] = 20 if rfc_match else (10 if mov_rfc else 0)
    if not rfc_match and mov_rfc:
        breakdown["notes"].append("RFC movimiento no coincide con CFDI")

    total = breakdown["amount"] + breakdown["date"] + breakdown["rfc"]
    return min(100, total), breakdown


def find_cfdi_candidates(
    issuer_id: int,
    movement: dict[str, Any],
    direction: str = "received",
    limit: int = 10,
) -> list[tuple[int, int, dict[str, Any]]]:
    """
    Busca CFDI candidatos para un movimiento (gasto → recibidas, ingreso → emitidas opcional).
    direction: 'received' para gastos (proveedor), 'issued' para ingresos (cliente).
    Returns list of (cfdi_id, score, breakdown).
    """
    if not table_exists(db(), "sat_cfdi"):
        return []
    amount = float(movement.get("deposito") or movement.get("retiro") or movement.get("amount") or 0)
    if amount <= 0:
        return []
    mov_date = movement.get("fecha") or ""
    period = (mov_date[:7]) if len(mov_date) >= 7 else None
    if not period:
        period = datetime.now().strftime("%Y-%m")

    rows = db_rows(
        """
        SELECT id, total, fecha_emision, rfc_emisor, rfc_receptor, uuid
        FROM sat_cfdi
        WHERE issuer_id = ? AND direction = ? AND total IS NOT NULL AND total >= 0.01
          AND fecha_emision IS NOT NULL AND substr(fecha_emision, 1, 7) = ?
        ORDER BY fecha_emision DESC
        LIMIT 500
        """,
        (issuer_id, direction, period),
    )
    issuer_rfc = None
    try:
        r = db_rows("SELECT rfc FROM issuers WHERE id = ? LIMIT 1", (issuer_id,))
        if r:
            issuer_rfc = (r[0].get("rfc") or "").strip()
    except Exception:
        pass

    candidates: list[tuple[int, int, dict]] = []
    for r in rows:
        cfdi_id = int(r["id"])
        score, breakdown = score_movement_cfdi(movement, dict(r), issuer_rfc)
        if score >= MIN_SCORE_THRESHOLD:
            candidates.append((cfdi_id, score, breakdown))
    candidates.sort(key=lambda x: -x[1])
    return candidates[:limit]


def save_suggested_matches(
    issuer_id: int,
    bank_movement_id: int,
    candidates: list[tuple[int, int, dict[str, Any]]],
    match_role: str = MATCH_ROLE_PAYMENT,
) -> None:
    """Persiste sugerencias en bank_invoice_matches (status=suggested)."""
    if not table_exists(db(), "bank_invoice_matches"):
        return
    conn = db()
    try:
        for cfdi_id, score, breakdown in candidates:
            amount = None
            conn.execute(
                """
                INSERT INTO bank_invoice_matches (issuer_id, bank_movement_id, cfdi_id, match_role, score, score_breakdown_json, matched_amount, status, is_partial, created_by, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 'system', datetime('now'), datetime('now'))
                """,
                (issuer_id, bank_movement_id, cfdi_id, match_role, score, json.dumps(breakdown), amount, STATUS_SUGGESTED),
            )
        conn.commit()
    finally:
        conn.close()


def confirm_match(match_id: int, issuer_id: int) -> bool:
    """Marca un match como confirmado. Verifica que pertenezca al issuer."""
    conn = db()
    try:
        row = conn.execute(
            "SELECT id FROM bank_invoice_matches WHERE id = ? AND issuer_id = ? LIMIT 1",
            (match_id, issuer_id),
        ).fetchone()
        if not row:
            return False
        conn.execute(
            "UPDATE bank_invoice_matches SET status = ?, updated_at = datetime('now') WHERE id = ?",
            (STATUS_CONFIRMED, match_id),
        )
        conn.commit()
        return True
    finally:
        conn.close()


def reject_match(match_id: int, issuer_id: int) -> bool:
    """Marca un match como rechazado."""
    conn = db()
    try:
        row = conn.execute(
            "SELECT id FROM bank_invoice_matches WHERE id = ? AND issuer_id = ? LIMIT 1",
            (match_id, issuer_id),
        ).fetchone()
        if not row:
            return False
        conn.execute(
            "UPDATE bank_invoice_matches SET status = ?, updated_at = datetime('now') WHERE id = ?",
            (STATUS_REJECTED, match_id),
        )
        conn.commit()
        return True
    finally:
        conn.close()
