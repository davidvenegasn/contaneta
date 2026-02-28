"""
Matching movimiento bancario ↔ CFDI (Fase 5). Scoring y persistencia en bank_invoice_matches.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from difflib import SequenceMatcher
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
    breakdown: dict[str, Any] = {"amount": 0, "date": 0, "rfc": 0, "text": 0, "notes": []}
    movement_amount = float(movement.get("deposito") or movement.get("retiro") or movement.get("amount") or 0)
    cfdi_total = float(cfdi.get("total") or 0)
    if movement_amount <= 0 or cfdi_total <= 0:
        breakdown["notes"].append("Monto inválido")
        return 0, breakdown

    diff = abs(movement_amount - cfdi_total)
    amount_ratio = min(movement_amount, cfdi_total) / max(movement_amount, cfdi_total)
    # Preferir tolerancia absoluta (PF): centavos/pesos. Luego ratio como fallback.
    if diff <= 0.50:
        breakdown["amount"] = 50
        breakdown["notes"].append("Monto coincide (±$0.50)")
    elif diff <= 1.00:
        breakdown["amount"] = 45
        breakdown["notes"].append("Monto muy cercano (±$1.00)")
    elif diff <= 5.00:
        breakdown["amount"] = 35
        breakdown["notes"].append("Monto cercano (±$5.00)")
    elif diff <= 10.00:
        breakdown["amount"] = 25
        breakdown["notes"].append("Monto aceptable (±$10.00)")
    elif amount_ratio >= 0.98:
        breakdown["amount"] = 25
    elif amount_ratio >= 0.95:
        breakdown["amount"] = 20
    elif amount_ratio >= 0.90:
        breakdown["amount"] = 12
    else:
        breakdown["notes"].append("Diferencia de monto alta")
        breakdown["amount"] = max(0, int(12 * amount_ratio))

    mov_date = _parse_date(movement.get("fecha"))
    cfdi_date = _parse_date(cfdi.get("fecha_emision"))
    if mov_date and cfdi_date:
        delta = abs((mov_date - cfdi_date).days)
        if delta == 0:
            breakdown["date"] = 30
            breakdown["notes"].append("Fecha coincide")
        elif delta == 1:
            breakdown["date"] = 24
            breakdown["notes"].append("Fecha ±1 día")
        elif delta == 2:
            breakdown["date"] = 18
            breakdown["notes"].append("Fecha ±2 días")
        elif delta == 3:
            breakdown["date"] = 12
            breakdown["notes"].append("Fecha ±3 días")
        elif delta <= 7:
            breakdown["date"] = 6
        else:
            breakdown["date"] = 0
    else:
        breakdown["date"] = 5
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
    breakdown["rfc"] = 15 if rfc_match else (5 if mov_rfc else 0)
    if not rfc_match and mov_rfc:
        breakdown["notes"].append("RFC movimiento no coincide con CFDI")

    # Similitud texto (sin IA): description vs concepto (si existe)
    mov_desc = (movement.get("normalized_description") or movement.get("descripcion") or movement.get("raw_description") or "").strip().upper()
    cfdi_concepto = (cfdi.get("concepto") or "").strip().upper()
    if mov_desc and cfdi_concepto:
        ratio = SequenceMatcher(a=mov_desc[:160], b=cfdi_concepto[:160]).ratio()
        if ratio >= 0.65:
            breakdown["text"] = 10
            breakdown["notes"].append("Texto similar")
        elif ratio >= 0.45:
            breakdown["text"] = 6
        elif ratio >= 0.30:
            breakdown["text"] = 3

    total = breakdown["amount"] + breakdown["date"] + breakdown["rfc"] + breakdown["text"]
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
    mov_date = (movement.get("fecha") or "").strip()
    mov_dt = _parse_date(mov_date)
    if mov_dt:
        d0 = mov_dt.strftime("%Y-%m-%d")
        # ventana ±3 días
        from datetime import timedelta
        d_from = (mov_dt - timedelta(days=3)).strftime("%Y-%m-%d")
        d_to = (mov_dt + timedelta(days=3)).strftime("%Y-%m-%d")
    else:
        d0 = ""
        d_from = ""
        d_to = ""

    # Filtro SQL por rango de monto + fecha cuando sea posible
    amt_from = max(0.0, amount - 10.0)
    amt_to = amount + 10.0
    if d_from and d_to:
        rows = db_rows(
            """
            SELECT id, total, fecha_emision, rfc_emisor, rfc_receptor, uuid, concepto
            FROM sat_cfdi
            WHERE issuer_id = ? AND direction = ? AND total IS NOT NULL AND total >= 0.01
              AND fecha_emision IS NOT NULL
              AND date(substr(fecha_emision,1,10)) BETWEEN date(?) AND date(?)
              AND total BETWEEN ? AND ?
            ORDER BY ABS(total - ?) ASC, fecha_emision DESC
            LIMIT 200
            """,
            (issuer_id, direction, d_from, d_to, amt_from, amt_to, amount),
        )
    else:
        period = (mov_date[:7]) if len(mov_date) >= 7 else datetime.now().strftime("%Y-%m")
        rows = db_rows(
            """
            SELECT id, total, fecha_emision, rfc_emisor, rfc_receptor, uuid, concepto
            FROM sat_cfdi
            WHERE issuer_id = ? AND direction = ? AND total IS NOT NULL AND total >= 0.01
              AND fecha_emision IS NOT NULL AND substr(fecha_emision, 1, 7) = ?
              AND total BETWEEN ? AND ?
            ORDER BY ABS(total - ?) ASC, fecha_emision DESC
            LIMIT 300
            """,
            (issuer_id, direction, period, amt_from, amt_to, amount),
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


def refresh_suggestions_for_month(issuer_id: int, ym: str, *, limit_movements: int = 2000) -> dict[str, Any]:
    """
    Recalcula sugerencias (status=suggested) para movimientos del mes.
    - No toca matches confirmed/rejected.
    - Borra sugerencias anteriores del mes (solo suggested) y las vuelve a generar.
    """
    issuer_id = int(issuer_id)
    ym = (ym or "").strip()[:7]
    if not ym:
        ym = datetime.now().strftime("%Y-%m")
    if not table_exists(db(), "bank_invoice_matches"):
        return {"ok": False, "message": "bank_invoice_matches no existe"}
    conn = db()
    try:
        try:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(bank_movements)").fetchall()}
        except Exception:
            cols = set()

        sel = ["id", "deposito", "retiro", "amount", "fecha"]
        if "descripcion" in cols:
            sel.append("descripcion")
        elif "descripcion_norm" in cols:
            sel.append("descripcion_norm AS descripcion")
        elif "descripcion_raw" in cols:
            sel.append("descripcion_raw AS descripcion")
        else:
            sel.append("'' AS descripcion")
        if "raw_description" in cols:
            sel.append("raw_description")
        if "normalized_description" in cols:
            sel.append("normalized_description")
        if "rfc_encontrado" in cols:
            sel.append("rfc_encontrado")
        if "counterparty_rfc_detected" in cols:
            sel.append("counterparty_rfc_detected")

        # Tomar movimientos del mes
        movs = conn.execute(
            f"""
            SELECT {", ".join(sel)}
            FROM bank_movements
            WHERE issuer_id = ? AND period_month = ?
            ORDER BY fecha DESC, id DESC
            LIMIT ?
            """,
            (issuer_id, ym, int(limit_movements)),
        ).fetchall()
        movs = [dict(r) if isinstance(r, dict) else dict(r) for r in movs]

        # Borrar sugerencias previas (solo suggested) de esos movimientos
        ids = [int(m["id"]) for m in movs if m.get("id")]
        if ids:
            # chunk para SQLITE max variables
            for i in range(0, len(ids), 400):
                chunk = ids[i : i + 400]
                q = ",".join(["?"] * len(chunk))
                conn.execute(
                    f"DELETE FROM bank_invoice_matches WHERE issuer_id = ? AND status = ? AND bank_movement_id IN ({q})",
                    (issuer_id, STATUS_SUGGESTED, *chunk),
                )

        issuer_rfc = None
        try:
            r = db_rows("SELECT rfc FROM issuers WHERE id = ? LIMIT 1", (issuer_id,))
            if r:
                issuer_rfc = (r[0].get("rfc") or "").strip()
        except Exception:
            issuer_rfc = None

        inserted = 0
        for m in movs:
            mid = int(m["id"])
            # Heurística: retiro -> received, deposito -> issued
            direction = "received" if float(m.get("retiro") or 0) > 0 else "issued"
            candidates = find_cfdi_candidates(issuer_id, m, direction=direction, limit=1)
            if not candidates:
                continue
            cfdi_id, score, breakdown = candidates[0]
            conn.execute(
                """
                INSERT INTO bank_invoice_matches (issuer_id, bank_movement_id, cfdi_id, match_role, score, score_breakdown_json, matched_amount, status, is_partial, created_by, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, NULL, ?, 0, 'system', datetime('now'), datetime('now'))
                """,
                (
                    issuer_id,
                    mid,
                    int(cfdi_id),
                    MATCH_ROLE_PAYMENT if direction == "received" else MATCH_ROLE_INCOME,
                    int(score),
                    json.dumps(breakdown, ensure_ascii=False),
                    STATUS_SUGGESTED,
                ),
            )
            inserted += 1

            # Opcional: reflejar en bank_movements.cfdi_match_status si existe
            try:
                conn.execute(
                    "UPDATE bank_movements SET cfdi_match_status = ? WHERE issuer_id = ? AND id = ?",
                    ("suggested" if score >= 80 else "pending", issuer_id, mid),
                )
            except Exception:
                pass

        conn.commit()
        return {"ok": True, "inserted": inserted, "movements": len(movs)}
    finally:
        conn.close()


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
            "UPDATE bank_invoice_matches SET status = ?, updated_at = datetime('now') WHERE id = ? AND issuer_id = ?",
            (STATUS_CONFIRMED, match_id, issuer_id),
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
            "UPDATE bank_invoice_matches SET status = ?, updated_at = datetime('now') WHERE id = ? AND issuer_id = ?",
            (STATUS_REJECTED, match_id, issuer_id),
        )
        conn.commit()
        return True
    finally:
        conn.close()
