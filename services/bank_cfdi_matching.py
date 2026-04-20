"""
Matching movimiento bancario ↔ CFDI (Fase 5). Scoring y persistencia en bank_invoice_matches.

Tier hierarchy:
  1. RFC match + amount match (±1%)        → 75-95
  2. Name match + amount match             → 65-85
  3. No RFC/name, exact amount + close date → 60-75
  4. Multi-movement sum → single invoice   → 70-80
"""
from __future__ import annotations

import json
import logging
import re
import unicodedata
from datetime import datetime, timedelta
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

# Legal suffixes to strip for name matching
_LEGAL_SUFFIXES = re.compile(
    r"\b(SA\s+DE\s+CV|SAPI\s+DE\s+CV|S\s+DE\s+RL\s+DE\s+CV|S\s+DE\s+RL|"
    r"SC\s+DE\s+RL|SC|SA|SAS|SAPI|AC|IAP|SPR\s+DE\s+RL)\b",
    re.IGNORECASE,
)
_STOPWORDS = {"DE", "LA", "LOS", "DEL", "EL", "Y", "LAS", "EN", "AL", "E", "CON", "POR", "A"}


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


def _norm_rfc(rfc: Optional[str]) -> str:
    if not rfc:
        return ""
    return re.sub(r"[\s\-]", "", rfc).strip().upper()


def _strip_accents(s: str) -> str:
    """Remove accents/diacritics from a string."""
    nfkd = unicodedata.normalize("NFD", s)
    return "".join(c for c in nfkd if unicodedata.category(c) != "Mn")


def _normalize_name(name: str) -> str:
    """Normalize a company/person name for comparison."""
    if not name:
        return ""
    name = _strip_accents(name).upper()
    name = _LEGAL_SUFFIXES.sub("", name)
    name = re.sub(r"[^A-Z0-9\s]", " ", name)
    return re.sub(r"\s+", " ", name).strip()


def _tokenize_name(name: str) -> list[str]:
    """Tokenize a normalized name, removing stopwords."""
    tokens = _normalize_name(name).split()
    return [t for t in tokens if t not in _STOPWORDS and len(t) > 1]


def _name_match_score(movement_text: str, cfdi_name: str) -> int:
    """
    Compare movement description text against CFDI emisor/receptor name.
    Returns: 25 (≥60% tokens match), 15 (≥40%), 0 otherwise.
    """
    cfdi_tokens = _tokenize_name(cfdi_name)
    if not cfdi_tokens:
        return 0
    mov_normalized = _normalize_name(movement_text)
    if not mov_normalized:
        return 0
    matched = sum(1 for t in cfdi_tokens if t in mov_normalized)
    ratio = matched / len(cfdi_tokens)
    if ratio >= 0.60:
        return 25
    if ratio >= 0.40:
        return 15
    return 0


def score_movement_cfdi(
    movement: dict[str, Any],
    cfdi: dict[str, Any],
    issuer_rfc: Optional[str] = None,
) -> tuple[int, dict[str, Any]]:
    """
    Calcula puntaje de coincidencia movimiento ↔ CFDI (0-105 capped to 100).

    Scoring breakdown:
      Amount:   0-40 pts
      RFC/Name: 0-35 pts
      Date:     0-20 pts
      Text:     0-10 pts
    """
    breakdown: dict[str, Any] = {"amount": 0, "date": 0, "rfc": 0, "text": 0, "notes": []}
    movement_amount = float(movement.get("deposito") or movement.get("retiro") or movement.get("amount") or 0)
    cfdi_total = float(cfdi.get("total") or 0)
    if movement_amount <= 0 or cfdi_total <= 0:
        breakdown["notes"].append("Monto inválido")
        return 0, breakdown

    # --- Amount scoring (0-40) ---
    diff = abs(movement_amount - cfdi_total)
    amount_ratio = min(movement_amount, cfdi_total) / max(movement_amount, cfdi_total)
    if diff <= 0.50:
        breakdown["amount"] = 40
        breakdown["notes"].append("Monto coincide (±$0.50)")
    elif diff <= 1.00:
        breakdown["amount"] = 37
        breakdown["notes"].append("Monto muy cercano (±$1.00)")
    elif diff <= 5.00:
        breakdown["amount"] = 30
        breakdown["notes"].append("Monto cercano (±$5.00)")
    elif diff <= 10.00:
        breakdown["amount"] = 22
        breakdown["notes"].append("Monto aceptable (±$10.00)")
    elif amount_ratio >= 0.98:
        breakdown["amount"] = 22
    elif amount_ratio >= 0.95:
        breakdown["amount"] = 18
    elif amount_ratio >= 0.90:
        breakdown["amount"] = 12
    elif amount_ratio >= 0.80:
        breakdown["amount"] = 6
    else:
        breakdown["notes"].append("Diferencia de monto alta")
        breakdown["amount"] = 0

    # --- RFC / Counterparty scoring (0-35) ---
    mov_rfc = _norm_rfc(movement.get("rfc_encontrado") or movement.get("counterparty_rfc_detected"))
    cfdi_emisor = _norm_rfc(cfdi.get("rfc_emisor"))
    cfdi_receptor = _norm_rfc(cfdi.get("rfc_receptor"))
    rfc_match = False
    if mov_rfc and (mov_rfc == cfdi_emisor or mov_rfc == cfdi_receptor):
        rfc_match = True
        breakdown["rfc"] = 35
        breakdown["notes"].append("RFC coincide")
    else:
        # Try name matching from movement description against CFDI name
        mov_desc = (
            movement.get("contraparte_hint")
            or movement.get("counterparty_name_detected")
            or movement.get("normalized_description")
            or movement.get("descripcion")
            or movement.get("descripcion_norm")
            or movement.get("raw_description")
            or movement.get("descripcion_raw")
            or ""
        )
        cfdi_name = cfdi.get("nombre_emisor") or cfdi.get("nombre_receptor") or ""
        # Try both emisor and receptor names, take best
        name_score = 0
        for name_field in ("nombre_emisor", "nombre_receptor"):
            n = cfdi.get(name_field) or ""
            if n:
                s = _name_match_score(mov_desc, n)
                if s > name_score:
                    name_score = s
        if name_score >= 25:
            breakdown["rfc"] = 25
            breakdown["notes"].append("Nombre contraparte coincide con CFDI")
        elif name_score >= 15:
            breakdown["rfc"] = 15
            breakdown["notes"].append("Nombre contraparte parcialmente coincide")
        elif mov_rfc:
            breakdown["rfc"] = 3
            breakdown["notes"].append("RFC detectado pero no coincide")
        else:
            breakdown["rfc"] = 0

    # --- Date scoring (0-20) ---
    mov_date = _parse_date(movement.get("fecha"))
    cfdi_date = _parse_date(cfdi.get("fecha_emision"))
    if mov_date and cfdi_date:
        delta = abs((mov_date - cfdi_date).days)
        if delta == 0:
            breakdown["date"] = 20
            breakdown["notes"].append("Fecha coincide")
        elif delta <= 1:
            breakdown["date"] = 18
            breakdown["notes"].append("Fecha ±1 día")
        elif delta <= 3:
            breakdown["date"] = 14
            breakdown["notes"].append("Fecha ±3 días")
        elif delta <= 7:
            breakdown["date"] = 10
            breakdown["notes"].append("Fecha ±7 días")
        elif delta <= 15:
            breakdown["date"] = 6
            breakdown["notes"].append("Fecha ±15 días")
        elif delta <= 30:
            breakdown["date"] = 3
            breakdown["notes"].append("Fecha ±30 días")
        else:
            breakdown["date"] = 0
    else:
        breakdown["date"] = 3
        breakdown["notes"].append("Fecha no parseable")

    # --- Text similarity scoring (0-10) ---
    mov_desc = (
        movement.get("normalized_description")
        or movement.get("descripcion")
        or movement.get("raw_description")
        or ""
    ).strip().upper()
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
    Two-pass CFDI candidate search for a bank movement.

    Pass 1: RFC-based (wide date/amount window) — if movement has RFC
    Pass 2: Amount+Date based (moderate window) — always runs

    Merges, deduplicates by cfdi_id, scores all, returns top N.
    """
    if not table_exists(db(), "sat_cfdi"):
        return []
    amount = float(movement.get("deposito") or movement.get("retiro") or movement.get("amount") or 0)
    if amount <= 0:
        return []
    mov_date = (movement.get("fecha") or "").strip()
    mov_dt = _parse_date(mov_date)

    issuer_rfc = None
    try:
        r = db_rows("SELECT rfc FROM issuers WHERE id = ? LIMIT 1", (issuer_id,))
        if r:
            issuer_rfc = (r[0].get("rfc") or "").strip()
    except Exception:
        pass

    seen_ids: set[int] = set()
    all_rows: list[dict] = []

    # --- Pass 1: RFC-based (wide window) ---
    mov_rfc = _norm_rfc(movement.get("rfc_encontrado") or movement.get("counterparty_rfc_detected"))
    if mov_rfc and mov_dt:
        d_from_rfc = (mov_dt - timedelta(days=45)).strftime("%Y-%m-%d")
        d_to_rfc = (mov_dt + timedelta(days=15)).strftime("%Y-%m-%d")
        amt_lo_rfc = amount * 0.80
        amt_hi_rfc = amount * 1.20
        rows_rfc = db_rows(
            """
            SELECT id, total, fecha_emision, rfc_emisor, nombre_emisor,
                   rfc_receptor, nombre_receptor, uuid, concepto
            FROM sat_cfdi
            WHERE issuer_id = ? AND direction = ?
              AND total IS NOT NULL AND total >= 0.01
              AND fecha_emision IS NOT NULL
              AND (rfc_emisor = ? OR rfc_receptor = ?)
              AND date(substr(fecha_emision,1,10)) BETWEEN date(?) AND date(?)
              AND total BETWEEN ? AND ?
            ORDER BY ABS(total - ?) ASC
            LIMIT 100
            """,
            (issuer_id, direction, mov_rfc, mov_rfc, d_from_rfc, d_to_rfc,
             amt_lo_rfc, amt_hi_rfc, amount),
        )
        for r in rows_rfc:
            cid = int(r["id"])
            if cid not in seen_ids:
                seen_ids.add(cid)
                all_rows.append(dict(r))

    # --- Pass 2: Amount+Date (moderate window) ---
    if mov_dt:
        d_from = (mov_dt - timedelta(days=15)).strftime("%Y-%m-%d")
        d_to = (mov_dt + timedelta(days=7)).strftime("%Y-%m-%d")
        amt_lo = amount * 0.95
        amt_hi = amount * 1.05
        rows_amt = db_rows(
            """
            SELECT id, total, fecha_emision, rfc_emisor, nombre_emisor,
                   rfc_receptor, nombre_receptor, uuid, concepto
            FROM sat_cfdi
            WHERE issuer_id = ? AND direction = ?
              AND total IS NOT NULL AND total >= 0.01
              AND fecha_emision IS NOT NULL
              AND date(substr(fecha_emision,1,10)) BETWEEN date(?) AND date(?)
              AND total BETWEEN ? AND ?
            ORDER BY ABS(total - ?) ASC
            LIMIT 200
            """,
            (issuer_id, direction, d_from, d_to, amt_lo, amt_hi, amount),
        )
        for r in rows_amt:
            cid = int(r["id"])
            if cid not in seen_ids:
                seen_ids.add(cid)
                all_rows.append(dict(r))
    else:
        # Fallback: period-based search
        period = (mov_date[:7]) if len(mov_date) >= 7 else datetime.now().strftime("%Y-%m")
        amt_lo = amount * 0.95
        amt_hi = amount * 1.05
        rows_fb = db_rows(
            """
            SELECT id, total, fecha_emision, rfc_emisor, nombre_emisor,
                   rfc_receptor, nombre_receptor, uuid, concepto
            FROM sat_cfdi
            WHERE issuer_id = ? AND direction = ?
              AND total IS NOT NULL AND total >= 0.01
              AND fecha_emision IS NOT NULL AND substr(fecha_emision, 1, 7) = ?
              AND total BETWEEN ? AND ?
            ORDER BY ABS(total - ?) ASC
            LIMIT 300
            """,
            (issuer_id, direction, period, amt_lo, amt_hi, amount),
        )
        for r in rows_fb:
            cid = int(r["id"])
            if cid not in seen_ids:
                seen_ids.add(cid)
                all_rows.append(dict(r))

    # Score all candidates
    candidates: list[tuple[int, int, dict]] = []
    for r in all_rows:
        cfdi_id = int(r["id"])
        score, breakdown = score_movement_cfdi(movement, r, issuer_rfc)
        if score >= MIN_SCORE_THRESHOLD:
            candidates.append((cfdi_id, score, breakdown))
    candidates.sort(key=lambda x: -x[1])
    return candidates[:limit]


def find_multi_movement_matches(
    issuer_id: int,
    ym: str,
    conn=None,
) -> list[dict[str, Any]]:
    """
    Tier 4: Find groups of unmatched movements from the same RFC/name
    whose amounts sum to a single invoice total (±1%).

    Returns list of match dicts ready for insertion.
    """
    close_conn = False
    if conn is None:
        conn = db()
        close_conn = True
    try:
        if not table_exists(conn, "sat_cfdi"):
            return []

        # Get unmatched expense movements with RFC for this month
        try:
            cols = {r["name"] for r in conn.execute("PRAGMA table_info(bank_movements)").fetchall()}
        except Exception:
            return []

        has_rfc_encontrado = "rfc_encontrado" in cols
        has_counterparty_rfc = "counterparty_rfc_detected" in cols
        if not has_rfc_encontrado and not has_counterparty_rfc:
            return []

        rfc_col = "rfc_encontrado" if has_rfc_encontrado else "counterparty_rfc_detected"

        # Find movements that don't already have a high-score match
        matched_mov_ids = conn.execute(
            """
            SELECT DISTINCT bank_movement_id FROM bank_invoice_matches
            WHERE issuer_id = ? AND status IN (?, ?) AND score >= 70
            """,
            (issuer_id, STATUS_SUGGESTED, STATUS_CONFIRMED),
        ).fetchall()
        exclude_ids = {int(r[0]) for r in matched_mov_ids}

        movs = conn.execute(
            f"""
            SELECT id, retiro, fecha, {rfc_col} as rfc_detected
            FROM bank_movements
            WHERE issuer_id = ? AND period_month = ?
              AND retiro > 0 AND {rfc_col} IS NOT NULL AND {rfc_col} != ''
            ORDER BY {rfc_col}, fecha
            """,
            (issuer_id, ym),
        ).fetchall()
        movs = [dict(r) for r in movs]
        movs = [m for m in movs if m["id"] not in exclude_ids]

        # Group by RFC
        from collections import defaultdict
        rfc_groups: dict[str, list[dict]] = defaultdict(list)
        for m in movs:
            rfc = _norm_rfc(m.get("rfc_detected"))
            if rfc:
                rfc_groups[rfc].append(m)

        results: list[dict] = []
        for rfc, group_movs in rfc_groups.items():
            if len(group_movs) < 2:
                continue
            total_sum = sum(float(m.get("retiro") or 0) for m in group_movs)
            if total_sum <= 0:
                continue
            # Search for a CFDI matching this sum (±1%)
            lo = total_sum * 0.99
            hi = total_sum * 1.01
            cfdis = conn.execute(
                """
                SELECT id, total, fecha_emision, rfc_emisor, nombre_emisor,
                       rfc_receptor, nombre_receptor, uuid
                FROM sat_cfdi
                WHERE issuer_id = ? AND direction = 'received'
                  AND total BETWEEN ? AND ?
                  AND (rfc_emisor = ? OR rfc_receptor = ?)
                LIMIT 5
                """,
                (issuer_id, lo, hi, rfc, rfc),
            ).fetchall()
            if not cfdis:
                continue
            cfdi = dict(cfdis[0])
            cfdi_id = int(cfdi["id"])
            for m in group_movs:
                results.append({
                    "bank_movement_id": int(m["id"]),
                    "cfdi_id": cfdi_id,
                    "score": 80,
                    "breakdown": {
                        "amount": 30, "rfc": 35, "date": 10, "text": 5,
                        "notes": [f"Multi-movimiento: {len(group_movs)} movimientos suman ${total_sum:.2f}"],
                    },
                    "is_partial": 1,
                    "matched_amount": float(m.get("retiro") or 0),
                })
        return results
    finally:
        if close_conn:
            conn.close()


def refresh_suggestions_for_month(issuer_id: int, ym: str, *, limit_movements: int = 2000) -> dict[str, Any]:
    """
    Recalcula sugerencias (status=suggested) para movimientos del mes.
    - No toca matches confirmed/rejected.
    - Borra sugerencias anteriores del mes (solo suggested) y las vuelve a generar.
    - Saves top 3 candidates per movement.
    - Runs multi-movement matching (Tier 4) after individual pass.
    - Matches both expenses (retiro → received) and income (deposito → issued).
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
            cols = {r["name"] for r in conn.execute("PRAGMA table_info(bank_movements)").fetchall()}
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
        if "contraparte_hint" in cols:
            sel.append("contraparte_hint")
        if "counterparty_name_detected" in cols:
            sel.append("counterparty_name_detected")

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
        movs = [dict(r) for r in movs]

        # Borrar sugerencias previas (solo suggested) de esos movimientos
        ids = [int(m["id"]) for m in movs if m.get("id")]
        if ids:
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
            retiro = float(m.get("retiro") or 0)
            deposito = float(m.get("deposito") or 0)
            # Match both directions: retiro → received, deposito → issued
            if retiro > 0:
                candidates = find_cfdi_candidates(issuer_id, m, direction="received", limit=3)
            elif deposito > 0:
                candidates = find_cfdi_candidates(issuer_id, m, direction="issued", limit=3)
            else:
                continue
            if not candidates:
                continue

            direction = "received" if retiro > 0 else "issued"
            match_role = MATCH_ROLE_PAYMENT if direction == "received" else MATCH_ROLE_INCOME

            for cfdi_id, score, breakdown in candidates:
                conn.execute(
                    """
                    INSERT INTO bank_invoice_matches (issuer_id, bank_movement_id, cfdi_id, match_role, score, score_breakdown_json, matched_amount, status, is_partial, created_by, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, NULL, ?, 0, 'system', datetime('now'), datetime('now'))
                    """,
                    (
                        issuer_id,
                        mid,
                        int(cfdi_id),
                        match_role,
                        int(score),
                        json.dumps(breakdown, ensure_ascii=False),
                        STATUS_SUGGESTED,
                    ),
                )
                inserted += 1

            # Update cfdi_match_status based on best score
            best_score = candidates[0][1]
            try:
                conn.execute(
                    "UPDATE bank_movements SET cfdi_match_status = ? WHERE issuer_id = ? AND id = ?",
                    ("suggested" if best_score >= 80 else "pending", issuer_id, mid),
                )
            except Exception:
                pass

        # --- Tier 4: Multi-movement matches ---
        try:
            multi_matches = find_multi_movement_matches(issuer_id, ym, conn=conn)
            for mm in multi_matches:
                conn.execute(
                    """
                    INSERT INTO bank_invoice_matches (issuer_id, bank_movement_id, cfdi_id, match_role, score, score_breakdown_json, matched_amount, status, is_partial, created_by, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'system', datetime('now'), datetime('now'))
                    """,
                    (
                        issuer_id,
                        mm["bank_movement_id"],
                        mm["cfdi_id"],
                        MATCH_ROLE_PAYMENT,
                        mm["score"],
                        json.dumps(mm["breakdown"], ensure_ascii=False),
                        mm["matched_amount"],
                        STATUS_SUGGESTED,
                        mm["is_partial"],
                    ),
                )
                inserted += 1
        except Exception as e:
            logger.warning("Multi-movement matching failed: %s", e)

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
