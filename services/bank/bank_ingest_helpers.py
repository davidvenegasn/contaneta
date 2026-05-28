"""Shared helpers for bank statement ingestion: metadata extraction, validation, movement mapping."""
from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timezone
from typing import Any, Optional

from database import has_column
from services.bank.bank_accounts import get_account_raw as bank_get_account
from services.bank.bank_preview_models import compute_dedupe_fingerprint

logger = logging.getLogger(__name__)

PARSER_NAME = "bank_preview_pipeline"
PARSER_VERSION = "1"
STATUS_ACCEPTED = "accepted"
STATUS_REJECTED_RFC = "rejected_rfc_mismatch"
STATUS_REJECTED_ACCOUNT = "rejected_account_mismatch"
STATUS_REJECTED_PERIOD = "rejected_period_invalid"


def _norm_rfc(rfc: Optional[str]) -> str:
    """Normaliza RFC para comparación: strip, upper, sin espacios."""
    if not rfc or not isinstance(rfc, str):
        return ""
    return re.sub(r"\s+", "", (rfc or "").strip().upper())


def extract_statement_metadata(preview_result: dict[str, Any]) -> dict[str, Any]:
    """
    Extrae metadata del resultado de parse_bank_statement_preview.
    Incluye: detected_holder_name, detected_holder_rfc, period_month, statement_year, statement_month,
    account_last4, bank_name, movements_count, total_deposito, total_retiro.
    """
    meta: dict[str, Any] = {
        "detected_holder_name": None,
        "detected_holder_rfc": None,
        "period_month": None,
        "statement_year": None,
        "statement_month": None,
        "account_last4": None,
        "bank_name": None,
        "movements_count": 0,
        "total_deposito": 0.0,
        "total_retiro": 0.0,
        "opening_balance": None,
        "closing_balance": None,
    }
    fs = preview_result.get("file_summary") or {}
    meta["detected_holder_name"] = (fs.get("account_holder_name") or "").strip() or None
    meta["detected_holder_rfc"] = (fs.get("account_holder_rfc") or "").strip() or None
    meta["bank_name"] = (fs.get("bank_name") or "").strip() or None
    meta["movements_count"] = int(fs.get("movements_count") or 0)
    meta["total_deposito"] = float(fs.get("total_deposito") or 0)
    meta["total_retiro"] = float(fs.get("total_retiro") or 0)
    meta["opening_balance"] = fs.get("opening_balance")
    meta["closing_balance"] = fs.get("closing_balance")
    meta["account_last4"] = (fs.get("account_last4") or "").strip() or None

    period_start = (fs.get("period_start") or "").strip()
    period_end = (fs.get("period_end") or "").strip()
    if period_start and len(period_start) >= 7:
        meta["period_month"] = period_start[:7]
        try:
            meta["statement_year"] = int(period_start[:4])
            meta["statement_month"] = int(period_start[5:7])
        except Exception:
            pass
    elif period_end and len(period_end) >= 7:
        meta["period_month"] = period_end[:7]
        try:
            meta["statement_year"] = int(period_end[:4])
            meta["statement_month"] = int(period_end[5:7])
        except Exception:
            pass
    else:
        # Fallback: detect from movement dates
        movements = preview_result.get("movements") or []
        dates = sorted(
            set(
                (m.get("fecha") or "").strip()[:10]
                for m in movements
                if (m.get("fecha") or "").strip()[:10]
            )
        )
        if dates:
            last = dates[-1]
            meta["period_month"] = last[:7]
            try:
                meta["statement_year"] = int(last[:4])
                meta["statement_month"] = int(last[5:7])
            except Exception:
                pass
    return meta


def validate_statement_ownership(
    issuer_id: int,
    bank_account_id: int,
    metadata: dict[str, Any],
    expected_issuer_rfc: Optional[str] = None,
) -> tuple[bool, str, Optional[str]]:
    """
    Valida que el estado de cuenta corresponda al RFC/cuenta del usuario.
    Returns (ok, status, rejection_reason).
    """
    account = bank_get_account(bank_account_id, issuer_id) if bank_account_id else None
    if not account:
        return False, STATUS_REJECTED_ACCOUNT, "Cuenta bancaria no encontrada o no pertenece al usuario."

    expected_rfc = _norm_rfc(expected_issuer_rfc or (account.get("rfc_titular") or ""))
    if not expected_rfc:
        expected_rfc = _norm_rfc(expected_issuer_rfc or "")

    detected_rfc = _norm_rfc(metadata.get("detected_holder_rfc"))
    detected_name = (metadata.get("detected_holder_name") or "").strip()
    account_last4 = (str(account.get("account_last4") or "").strip().replace(" ", ""))[-4:]
    clabe = (str(account.get("clabe") or "").strip().replace(" ", ""))

    if expected_rfc and detected_rfc and expected_rfc != detected_rfc:
        return False, STATUS_REJECTED_RFC, (
            f"El RFC del estado de cuenta ({detected_rfc}) no coincide con el RFC esperado ({expected_rfc})."
        )

    if account_last4 or clabe:
        detected_last4 = (metadata.get("account_last4") or "").strip().replace(" ", "")[-4:]
        if account_last4 and detected_last4 and account_last4 != detected_last4:
            return False, STATUS_REJECTED_ACCOUNT, (
                f"Los últimos 4 dígitos de la cuenta del PDF ({detected_last4 or 'no detectados'}) no coinciden con la cuenta seleccionada ({account_last4})."
            )

    period = (metadata.get("period_month") or "").strip()
    if not period and metadata.get("movements_count", 0) > 0:
        period = datetime.now(timezone.utc).strftime("%Y-%m")
    if not period:
        return False, STATUS_REJECTED_PERIOD, "No se pudo detectar el periodo del estado de cuenta."

    return True, STATUS_ACCEPTED, None


def _month_from_fecha(fecha: Optional[str]) -> Optional[str]:
    """Extrae YYYY-MM de una fecha (2026-01-01, 01/01/2026, etc.). None si no se puede."""
    f = (fecha or "").strip()[:32]
    if not f:
        return None
    if re.match(r"\d{4}-\d{2}-\d{2}", f):
        return f[:7]
    m = re.match(r"(\d{2})[/\-](\d{2})[/\-](\d{2,4})", f)
    if m:
        d, mo, y = m.group(1), m.group(2), m.group(3)
        y = int(y) if len(y) == 4 else 2000 + int(y) % 100
        try:
            return f"{y:04d}-{int(mo):02d}"
        except ValueError:
            return None
    return None


def _normalize_rfc(rfc: str | None) -> str:
    """Normalize RFC: strip, uppercase, treat 'ND' and similar as empty."""
    if not rfc:
        return ""
    r = rfc.strip().upper()[:20]
    if r in ("ND", "N/D", "NA", "N/A", "NO DISPONIBLE", "SIN RFC", ""):
        return ""
    return r


def _movement_to_row(
    m: dict,
    issuer_id: int,
    bank_statement_id: int,
    bank_account_id: int,
    period_month: str,
    idx: int,
) -> dict[str, Any]:
    """Mapea un movimiento preview a fila para bank_movements. period_month por movimiento = mes de su fecha."""
    dep = float(m.get("monto_deposito") or 0)
    ret = float(m.get("monto_retiro") or 0)
    amount = dep if dep > 0 else ret
    direction = "credit" if dep > 0 else "debit"
    raw_desc = (m.get("raw_text_original") or m.get("concepto_resumen") or "")[:2000]
    norm_desc = (m.get("raw_text_normalized") or m.get("concepto_resumen") or "")[:2000]
    fp = m.get("dedupe_fingerprint") or compute_dedupe_fingerprint(m)
    fecha_str = (m.get("fecha") or "")[:32]
    # Mes del movimiento = fecha del movimiento (cada fila a su mes); fallback = periodo del estado
    row_period_month = _month_from_fecha(fecha_str) or period_month
    return {
        "issuer_id": issuer_id,
        "bank_statement_id": bank_statement_id,
        "bank_account_id": bank_account_id,
        "statement_file_id": str(bank_statement_id),  # legacy compat; new flow uses bank_statement_id
        "period_month": row_period_month,
        "movement_index": idx,
        "fecha": (m.get("fecha") or "")[:32],
        "descripcion": (m.get("concepto_resumen") or raw_desc)[:2000],
        "raw_description": raw_desc,
        "normalized_description": norm_desc,
        "deposito": dep if dep else None,
        "retiro": ret if ret else None,
        "saldo": m.get("saldo"),
        "amount": amount,
        "direction": direction,
        "tipo": (m.get("tipo_movimiento") or "DESCONOCIDO")[:32],
        "categoria": (m.get("categoria_sugerida") or "OTROS")[:200],
        "metodo_hint": (m.get("canal") or "")[:64],
        "contraparte_hint": (m.get("contraparte_nombre") or "")[:200],
        "rfc_encontrado": _normalize_rfc(m.get("rfc_detectado")),
        "counterparty_name_detected": (m.get("contraparte_nombre") or "")[:200],
        "counterparty_rfc_detected": _normalize_rfc(m.get("rfc_detectado")),
        "confidence_score": int(m.get("confianza_clasificacion") or 0),
        "source_page_first": None,
        "duplicate_hash": fp[:64] if fp else None,
        "is_possible_duplicate": 1 if m.get("posible_duplicado") else 0,
        "requires_cfdi": 1 if _movement_requires_cfdi(m) else 0,
        "cfdi_match_status": "pending",
        "impacta_contabilidad": 0 if m.get("impacta_contabilidad") is False or m.get("impacta_contabilidad") == 0 else 1,
        "own_account_alias": (m.get("own_account_alias") or "")[:200] or None,
    }


def _movement_dedup_hash(
    issuer_id: int, fecha: str, descripcion: str, deposito: Optional[float], retiro: Optional[float]
) -> str:
    """Hash para deduplicar movimientos: mismo issuer + fecha + concepto + montos = mismo movimiento."""
    dep = f"{float(deposito or 0):.2f}"
    ret = f"{float(retiro or 0):.2f}"
    desc = (descripcion or "").strip()[:500].replace("\r", " ").replace("\n", " ")
    payload = f"{issuer_id}|{fecha or ''}|{desc}|{dep}|{ret}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _movement_requires_cfdi(m: dict) -> bool:
    """Heurística: gastos con monto y no financieros/traspaso propio suelen requerir CFDI."""
    if (m.get("tipo_movimiento") or "").upper() != "GASTO":
        return False
    if m.get("es_transferencia_propia_probable") or m.get("es_pago_tarjeta_probable"):
        return False
    return bool(m.get("monto_retiro") and float(m.get("monto_retiro") or 0) >= 0.01)


def _check_balance_mismatch(conn: Any, statement_id: int, metadata: dict[str, Any]) -> None:
    """Compare opening + movements vs closing balance. Update bank_statements if mismatch."""
    if not has_column(conn, "bank_statements", "has_balance_mismatch"):
        return
    opening = metadata.get("opening_balance")
    closing = metadata.get("closing_balance")
    if opening is None or closing is None:
        return
    try:
        opening = float(opening)
        closing = float(closing)
    except (TypeError, ValueError):
        return
    row = conn.execute(
        "SELECT COALESCE(SUM(deposito), 0) AS dep, COALESCE(SUM(retiro), 0) AS ret FROM bank_movements WHERE bank_statement_id = ?",
        (statement_id,),
    ).fetchone()
    sum_dep = float(row[0] if isinstance(row, (tuple, list)) else row["dep"])
    sum_ret = float(row[1] if isinstance(row, (tuple, list)) else row["ret"])
    computed = opening + sum_dep - sum_ret
    diff = abs(computed - closing)
    has_mismatch = 1 if diff > 0.01 else 0
    conn.execute(
        "UPDATE bank_statements SET has_balance_mismatch = ?, computed_closing_balance = ?, balance_diff = ? WHERE id = ?",
        (has_mismatch, round(computed, 2), round(diff, 2), statement_id),
    )


def _statement_fingerprint_preview(
    issuer_id: int,
    bank_account_id: int,
    period_month: str,
    bank_name: str,
    account_last4: str,
    movement_count: int,
    first_fp: str,
    last_fp: str,
) -> str:
    """Genera fingerprint para dedupe de estado de cuenta desde preview (sin PDF)."""
    payload = f"preview|{issuer_id}|{bank_account_id}|{period_month}|{(bank_name or '')}|{(account_last4 or '')}|{movement_count}|{first_fp}|{last_fp}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
