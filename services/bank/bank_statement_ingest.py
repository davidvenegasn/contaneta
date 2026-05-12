"""
Ingesta de estados de cuenta: extracción de metadata, validación RFC/cuenta/periodo y persistencia.
Fases 2 y 3 del módulo Movimientos.
"""
from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timezone
from typing import Any, Optional

from database import db, has_column, table_exists
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

    # Periodo: priorizar el explícito del encabezado (ej. "01/01/2026 al 31/01/2026").
    # No usar la primera fecha de movimientos: "Saldo anterior" suele ser 31 del mes anterior y falsea el mes.
    period_start = (fs.get("period_start") or "").strip()[:10]
    period_end = (fs.get("period_end") or "").strip()[:10]
    if period_start and period_end and re.match(r"\d{4}-\d{2}-\d{2}", period_start) and re.match(r"\d{4}-\d{2}-\d{2}", period_end):
        meta["period_month"] = period_end[:7]
        meta["period_start"] = period_start
        meta["period_end"] = period_end
        try:
            meta["statement_year"] = int(period_end[:4])
            meta["statement_month"] = int(period_end[5:7])
        except Exception:
            pass
    else:
        # Fallback: usar fechas de movimientos; preferir la ÚLTIMA (cierre del periodo), no la primera (Saldo anterior).
        movements = preview_result.get("movements") or []
        dates: list[str] = []
        for m in movements:
            desc = (
                (m.get("concepto_resumen") or m.get("raw_text_original") or m.get("descripcion")
                 or m.get("description_raw") or m.get("descripcion_corta") or "")
            ).upper()
            if "SALDO ANTERIOR" in desc:
                continue
            f = (m.get("fecha") or "").strip()[:10]
            if f and re.match(r"\d{4}-\d{2}-\d{2}", f):
                dates.append(f)
            elif f and re.match(r"\d{2}/\d{2}/\d{2,4}", f):
                try:
                    parts = f.replace("-", "/").split("/")
                    if len(parts) == 3:
                        d, mo, y = parts
                        y = int(y) if len(y) == 4 else 2000 + int(y) % 100
                        dates.append(f"{y:04d}-{int(mo):02d}-{int(d):02d}")
                except Exception:
                    pass
        if dates:
            dates.sort()
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
    """Hash para deduplicar movimientos: mismo issuer + fecha + concepto + montos = mismo movimiento (evita duplicados al subir el mismo edo. dos veces)."""
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


def ingest_bank_statement(
    issuer_id: int,
    bank_account_id: int,
    pdf_path: str,
    pdf_sha256: str,
    source_file_name: str,
    preview_result: dict[str, Any],
    expected_issuer_rfc: Optional[str] = None,
) -> dict[str, Any]:
    """
    Valida e ingesta un estado de cuenta: inserta bank_statements (con metadata) y bank_movements.
    Si ya existe un statement con el mismo issuer_id + source_pdf_sha256, devuelve ese statement_id sin reinsertar.
    Returns: { "ok": True, "statement_id": int, "movements_count": int } o { "ok": False, "rejection_reason": str, "status": str }.
    """
    metadata = extract_statement_metadata(preview_result)
    ok, status, rejection_reason = validate_statement_ownership(
        issuer_id, bank_account_id, metadata, expected_issuer_rfc
    )
    if not ok:
        return {"ok": False, "status": status, "rejection_reason": rejection_reason}

    movements = preview_result.get("movements") or []
    period_month = metadata.get("period_month") or datetime.now(timezone.utc).strftime("%Y-%m")
    conn = db()
    try:
        if not table_exists(conn, "bank_statements"):
            return {"ok": False, "status": "error", "rejection_reason": "Tabla bank_statements no existe."}

        row = conn.execute(
            "SELECT id FROM bank_statements WHERE issuer_id = ? AND source_pdf_sha256 = ? LIMIT 1",
            (issuer_id, pdf_sha256),
        ).fetchone()
        if row:
            statement_id = int(row["id"])
            conn.close()
            return {"ok": True, "statement_id": statement_id, "movements_count": 0, "duplicate": True}

        # Columnas nuevas (migración 021): si existen, las llenamos
        use_021 = has_column(conn, "bank_statements", "status")
        now = datetime.now(timezone.utc).isoformat()

        if use_021:
            conn.execute(
                """
                INSERT INTO bank_statements (
                    issuer_id, bank_name, account_last4, period_start, period_end, source_pdf_path, source_pdf_sha256,
                    source_file_name, parser_name, parser_version, detected_holder_name, detected_holder_rfc,
                    detected_account_last4, period_month, statement_year, statement_month,
                    opening_balance, closing_balance, status, total_movements, bank_account_id, updated_at, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                """,
                (
                    issuer_id,
                    metadata.get("bank_name"),
                    metadata.get("account_last4"),
                    period_month + "-01",
                    period_month + "-31",
                    pdf_path,
                    pdf_sha256,
                    source_file_name[:255],
                    PARSER_NAME,
                    PARSER_VERSION,
                    metadata.get("detected_holder_name"),
                    metadata.get("detected_holder_rfc"),
                    metadata.get("account_last4"),
                    period_month,
                    metadata.get("statement_year"),
                    metadata.get("statement_month"),
                    metadata.get("opening_balance"),
                    metadata.get("closing_balance"),
                    STATUS_ACCEPTED,
                    len(movements),
                    bank_account_id,
                    now,
                ),
            )
        else:
            conn.execute(
                """
                INSERT INTO bank_statements (issuer_id, source_pdf_path, source_pdf_sha256, created_at)
                VALUES (?, ?, ?, datetime('now'))
                """,
                (issuer_id, pdf_path, pdf_sha256),
            )
        _lid_row = conn.execute("SELECT last_insert_rowid() AS lid").fetchone()
        statement_id = _lid_row["lid"]

        if not table_exists(conn, "bank_movements"):
            conn.commit()
            conn.close()
            return {"ok": True, "statement_id": statement_id, "movements_count": 0}

        mov_cols_021 = has_column(conn, "bank_movements", "bank_statement_id")
        has_dup_col = has_column(conn, "bank_movements", "duplicate_hash") and has_column(
            conn, "bank_movements", "bank_account_id"
        )
        has_impacta = has_column(conn, "bank_movements", "impacta_contabilidad")
        has_movement_hash = has_column(conn, "bank_movements", "movement_hash")
        inserted_count = 0
        duplicate_movements_count = 0
        duplicate_samples: list[dict] = []
        for i, m in enumerate(movements):
            row = _movement_to_row(m, issuer_id, statement_id, bank_account_id, period_month, i + 1)
            # Dedup by movement_hash (issuer+fecha+desc+montos) — works cross-file
            if has_movement_hash:
                global_hash = _movement_dedup_hash(
                    issuer_id,
                    row["fecha"],
                    row["descripcion"],
                    row.get("deposito"),
                    row.get("retiro"),
                )
                existing = conn.execute(
                    "SELECT 1 FROM bank_movements WHERE issuer_id = ? AND movement_hash = ? LIMIT 1",
                    (issuer_id, global_hash),
                ).fetchone()
                if existing:
                    duplicate_movements_count += 1
                    if len(duplicate_samples) < 5:
                        duplicate_samples.append({"fecha": row["fecha"], "descripcion": (row["descripcion"] or "")[:80], "deposito": row.get("deposito"), "retiro": row.get("retiro")})
                    continue
                row["movement_hash"] = global_hash
            # Fallback: dedup by duplicate_hash (fingerprint within same account)
            dup_hash = row.get("duplicate_hash")
            if has_dup_col and dup_hash:
                existing = conn.execute(
                    "SELECT 1 FROM bank_movements WHERE bank_account_id = ? AND duplicate_hash = ? LIMIT 1",
                    (bank_account_id, dup_hash),
                ).fetchone()
                if existing:
                    duplicate_movements_count += 1
                    if len(duplicate_samples) < 5:
                        duplicate_samples.append({"fecha": row["fecha"], "descripcion": (row["descripcion"] or "")[:80], "deposito": row.get("deposito"), "retiro": row.get("retiro")})
                    continue
            if mov_cols_021 and has_movement_hash:
                conn.execute(
                    """
                    INSERT INTO bank_movements (
                        issuer_id, statement_file_id, bank_statement_id, bank_account_id, period_month, movement_index,
                        fecha, descripcion, raw_description, normalized_description, deposito, retiro, saldo,
                        amount, direction, tipo, categoria, metodo_hint, contraparte_hint, rfc_encontrado,
                        counterparty_name_detected, counterparty_rfc_detected, confidence_score,
                        duplicate_hash, is_possible_duplicate, requires_cfdi, cfdi_match_status, movement_hash, created_at, updated_at
                        {', impacta_contabilidad' if has_impacta else ''}
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), ?
                        {', ?' if has_impacta else ''})
                    """,
                    (
                        row["issuer_id"],
                        row["statement_file_id"],
                        row["bank_statement_id"],
                        row["bank_account_id"],
                        row["period_month"],
                        row["movement_index"],
                        row["fecha"],
                        row["descripcion"],
                        row["raw_description"],
                        row["normalized_description"],
                        row["deposito"],
                        row["retiro"],
                        row["saldo"],
                        row["amount"],
                        row["direction"],
                        row["tipo"],
                        row["categoria"],
                        row["metodo_hint"],
                        row["contraparte_hint"],
                        row["rfc_encontrado"],
                        row["counterparty_name_detected"],
                        row["counterparty_rfc_detected"],
                        row["confidence_score"],
                        row["duplicate_hash"],
                        row["is_possible_duplicate"],
                        row["requires_cfdi"],
                        row["cfdi_match_status"],
                        row.get("movement_hash"),
                        now,
                        *([row["impacta_contabilidad"]] if has_impacta else []),
                    ),
                )
            elif mov_cols_021:
                conn.execute(
                    f"""
                    INSERT INTO bank_movements (
                        issuer_id, statement_file_id, bank_statement_id, bank_account_id, period_month, movement_index,
                        fecha, descripcion, raw_description, normalized_description, deposito, retiro, saldo,
                        amount, direction, tipo, categoria, metodo_hint, contraparte_hint, rfc_encontrado,
                        counterparty_name_detected, counterparty_rfc_detected, confidence_score,
                        duplicate_hash, is_possible_duplicate, requires_cfdi, cfdi_match_status, created_at, updated_at
                        {', impacta_contabilidad' if has_impacta else ''}
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), ?
                        {', ?' if has_impacta else ''})
                    """,
                    (
                        row["issuer_id"],
                        row["statement_file_id"],
                        row["bank_statement_id"],
                        row["bank_account_id"],
                        row["period_month"],
                        row["movement_index"],
                        row["fecha"],
                        row["descripcion"],
                        row["raw_description"],
                        row["normalized_description"],
                        row["deposito"],
                        row["retiro"],
                        row["saldo"],
                        row["amount"],
                        row["direction"],
                        row["tipo"],
                        row["categoria"],
                        row["metodo_hint"],
                        row["contraparte_hint"],
                        row["rfc_encontrado"],
                        row["counterparty_name_detected"],
                        row["counterparty_rfc_detected"],
                        row["confidence_score"],
                        row["duplicate_hash"],
                        row["is_possible_duplicate"],
                        row["requires_cfdi"],
                        row["cfdi_match_status"],
                        now,
                        *([row["impacta_contabilidad"]] if has_impacta else []),
                    ),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO bank_movements (issuer_id, statement_file_id, fecha, descripcion, deposito, retiro, saldo, tipo, categoria, metodo_hint, contraparte_hint, rfc_encontrado, confidence_score, source_page_first)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        row["issuer_id"],
                        row["statement_file_id"] or str(statement_id),
                        row["fecha"],
                        row["descripcion"],
                        row["deposito"],
                        row["retiro"],
                        row["saldo"],
                        row["tipo"],
                        row["categoria"],
                        row["metodo_hint"],
                        row["contraparte_hint"],
                        row["rfc_encontrado"],
                        row["confidence_score"],
                        row.get("source_page_first"),
                    ),
                )
            inserted_count += 1
        # Balance mismatch detection
        _check_balance_mismatch(conn, statement_id, metadata)
        conn.commit()
        return {
            "ok": True,
            "statement_id": statement_id,
            "movements_count": inserted_count,
            "inserted_count": inserted_count,
            "duplicate_movements_count": duplicate_movements_count,
            "duplicate_samples": duplicate_samples[:5],
        }
    except Exception as e:
        logger.exception("ingest_bank_statement: error issuer=%s", issuer_id)
        try:
            conn.rollback()
        except Exception:
            pass
        return {"ok": False, "status": "error", "rejection_reason": str(e)}
    finally:
        try:
            conn.close()
        except Exception:
            pass


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


def commit_preview_to_db(
    issuer_id: int,
    bank_account_id: int,
    file_summary: dict[str, Any],
    movements: list[dict[str, Any]],
    expected_issuer_rfc: Optional[str] = None,
) -> dict[str, Any]:
    """
    Persiste movimientos desde el preview (sin PDF). Reutiliza validación e ingest;
    usa fingerprint sintético para dedupe a nivel statement y duplicate_hash para movimientos.
    """
    preview_result: dict[str, Any] = {"file_summary": file_summary or {}, "movements": movements or []}
    metadata = extract_statement_metadata(preview_result)
    ok, status, rejection_reason = validate_statement_ownership(
        issuer_id, bank_account_id, metadata, expected_issuer_rfc
    )
    if not ok:
        return {"ok": False, "status": status, "rejection_reason": rejection_reason}

    movements_list = list(movements or [])
    period_month = metadata.get("period_month") or datetime.now(timezone.utc).strftime("%Y-%m")
    bank_name = (metadata.get("bank_name") or "")[:255]
    account_last4 = (metadata.get("account_last4") or "")[:32]

    first_fp = ""
    last_fp = ""
    if movements_list:
        first_fp = (movements_list[0].get("dedupe_fingerprint") or compute_dedupe_fingerprint(movements_list[0]))[:64]
        last_fp = (movements_list[-1].get("dedupe_fingerprint") or compute_dedupe_fingerprint(movements_list[-1]))[:64]
    synthetic_sha = _statement_fingerprint_preview(
        issuer_id, bank_account_id, period_month, bank_name, account_last4, len(movements_list), first_fp, last_fp
    )
    source_pdf_sha256 = "preview:" + synthetic_sha
    source_pdf_path = f"preview:commit:{period_month}:{bank_account_id}"

    conn = db()
    try:
        if not table_exists(conn, "bank_statements"):
            return {"ok": False, "status": "error", "rejection_reason": "Tabla bank_statements no existe."}

        row = conn.execute(
            "SELECT id FROM bank_statements WHERE issuer_id = ? AND source_pdf_sha256 = ? LIMIT 1",
            (issuer_id, source_pdf_sha256),
        ).fetchone()
        if row:
            conn.close()
            return {
                "ok": True,
                "statement_id": int(row["id"]),
                "inserted_count": 0,
                "duplicate_statement": True,
                "duplicate_movements_count": 0,
                "skipped_count": len(movements_list),
            }

        use_021 = has_column(conn, "bank_statements", "status")
        now = datetime.now(timezone.utc).isoformat()
        source_file_name = (file_summary.get("source_file_name") or file_summary.get("file_name") or "preview")[:255]

        if use_021:
            conn.execute(
                """
                INSERT INTO bank_statements (
                    issuer_id, bank_name, account_last4, period_start, period_end, source_pdf_path, source_pdf_sha256,
                    source_file_name, parser_name, parser_version, detected_holder_name, detected_holder_rfc,
                    detected_account_last4, period_month, statement_year, statement_month,
                    opening_balance, closing_balance, status, total_movements, bank_account_id, updated_at, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                """,
                (
                    issuer_id,
                    bank_name,
                    account_last4,
                    period_month + "-01",
                    period_month + "-31",
                    source_pdf_path,
                    source_pdf_sha256,
                    source_file_name,
                    PARSER_NAME,
                    PARSER_VERSION,
                    metadata.get("detected_holder_name"),
                    metadata.get("detected_holder_rfc"),
                    account_last4,
                    period_month,
                    metadata.get("statement_year"),
                    metadata.get("statement_month"),
                    metadata.get("opening_balance"),
                    metadata.get("closing_balance"),
                    STATUS_ACCEPTED,
                    len(movements_list),
                    bank_account_id,
                    now,
                ),
            )
        else:
            conn.execute(
                """
                INSERT INTO bank_statements (issuer_id, source_pdf_path, source_pdf_sha256, created_at)
                VALUES (?, ?, ?, datetime('now'))
                """,
                (issuer_id, source_pdf_path, source_pdf_sha256),
            )
        _lid_row = conn.execute("SELECT last_insert_rowid() AS lid").fetchone()
        statement_id = _lid_row["lid"]

        inserted_count = 0
        duplicate_movements_count = 0
        has_dup_col = has_column(conn, "bank_movements", "duplicate_hash") and has_column(
            conn, "bank_movements", "bank_account_id"
        )
        has_movement_hash = has_column(conn, "bank_movements", "movement_hash")

        if table_exists(conn, "bank_movements"):
            mov_cols_021 = has_column(conn, "bank_movements", "bank_statement_id")
            has_impacta = has_column(conn, "bank_movements", "impacta_contabilidad")
            for i, m in enumerate(movements_list):
                row_data = _movement_to_row(m, issuer_id, statement_id, bank_account_id, period_month, i + 1)
                if has_movement_hash:
                    global_hash = _movement_dedup_hash(
                        issuer_id,
                        row_data["fecha"],
                        row_data["descripcion"],
                        row_data.get("deposito"),
                        row_data.get("retiro"),
                    )
                    existing = conn.execute(
                        "SELECT 1 FROM bank_movements WHERE issuer_id = ? AND movement_hash = ? LIMIT 1",
                        (issuer_id, global_hash),
                    ).fetchone()
                    if existing:
                        duplicate_movements_count += 1
                        continue
                    row_data["movement_hash"] = global_hash
                dup_hash = row_data.get("duplicate_hash")
                if has_dup_col and dup_hash:
                    existing = conn.execute(
                        "SELECT 1 FROM bank_movements WHERE bank_account_id = ? AND duplicate_hash = ? LIMIT 1",
                        (bank_account_id, dup_hash),
                    ).fetchone()
                    if existing:
                        duplicate_movements_count += 1
                        continue
                if mov_cols_021:
                    if has_movement_hash:
                        conn.execute(
                            f"""
                            INSERT INTO bank_movements (
                                issuer_id, statement_file_id, bank_statement_id, bank_account_id, period_month, movement_index,
                                fecha, descripcion, raw_description, normalized_description, deposito, retiro, saldo,
                                amount, direction, tipo, categoria, metodo_hint, contraparte_hint, rfc_encontrado,
                                counterparty_name_detected, counterparty_rfc_detected, confidence_score,
                                duplicate_hash, is_possible_duplicate, requires_cfdi, cfdi_match_status, movement_hash, created_at, updated_at
                                {', impacta_contabilidad' if has_impacta else ''}
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), ?
                                {', ?' if has_impacta else ''})
                            """,
                            (
                                row_data["issuer_id"],
                                row_data["statement_file_id"],
                                row_data["bank_statement_id"],
                                row_data["bank_account_id"],
                                row_data["period_month"],
                                row_data["movement_index"],
                                row_data["fecha"],
                                row_data["descripcion"],
                                row_data["raw_description"],
                                row_data["normalized_description"],
                                row_data["deposito"],
                                row_data["retiro"],
                                row_data["saldo"],
                                row_data["amount"],
                                row_data["direction"],
                                row_data["tipo"],
                                row_data["categoria"],
                                row_data["metodo_hint"],
                                row_data["contraparte_hint"],
                                row_data["rfc_encontrado"],
                                row_data["counterparty_name_detected"],
                                row_data["counterparty_rfc_detected"],
                                row_data["confidence_score"],
                                row_data["duplicate_hash"],
                                row_data["is_possible_duplicate"],
                                row_data["requires_cfdi"],
                                row_data["cfdi_match_status"],
                                row_data.get("movement_hash"),
                                now,
                                *([row_data["impacta_contabilidad"]] if has_impacta else []),
                            ),
                        )
                    else:
                        conn.execute(
                            f"""
                            INSERT INTO bank_movements (
                                issuer_id, statement_file_id, bank_statement_id, bank_account_id, period_month, movement_index,
                                fecha, descripcion, raw_description, normalized_description, deposito, retiro, saldo,
                                amount, direction, tipo, categoria, metodo_hint, contraparte_hint, rfc_encontrado,
                                counterparty_name_detected, counterparty_rfc_detected, confidence_score,
                                duplicate_hash, is_possible_duplicate, requires_cfdi, cfdi_match_status, created_at, updated_at
                                {', impacta_contabilidad' if has_impacta else ''}
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), ?
                                {', ?' if has_impacta else ''})
                            """,
                            (
                                row_data["issuer_id"],
                                row_data["statement_file_id"],
                                row_data["bank_statement_id"],
                                row_data["bank_account_id"],
                                row_data["period_month"],
                                row_data["movement_index"],
                                row_data["fecha"],
                                row_data["descripcion"],
                                row_data["raw_description"],
                                row_data["normalized_description"],
                                row_data["deposito"],
                                row_data["retiro"],
                                row_data["saldo"],
                                row_data["amount"],
                                row_data["direction"],
                                row_data["tipo"],
                                row_data["categoria"],
                                row_data["metodo_hint"],
                                row_data["contraparte_hint"],
                                row_data["rfc_encontrado"],
                                row_data["counterparty_name_detected"],
                                row_data["counterparty_rfc_detected"],
                                row_data["confidence_score"],
                                row_data["duplicate_hash"],
                                row_data["is_possible_duplicate"],
                                row_data["requires_cfdi"],
                                row_data["cfdi_match_status"],
                                now,
                                *([row_data["impacta_contabilidad"]] if has_impacta else []),
                            ),
                        )
                else:
                    if has_movement_hash:
                        conn.execute(
                            """
                            INSERT INTO bank_movements (issuer_id, statement_file_id, fecha, descripcion, deposito, retiro, saldo, tipo, categoria, metodo_hint, contraparte_hint, rfc_encontrado, confidence_score, source_page_first, movement_hash)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                row_data["issuer_id"],
                                row_data["statement_file_id"] or str(statement_id),
                                row_data["fecha"],
                                row_data["descripcion"],
                                row_data["deposito"],
                                row_data["retiro"],
                                row_data["saldo"],
                                row_data["tipo"],
                                row_data["categoria"],
                                row_data["metodo_hint"],
                                row_data["contraparte_hint"],
                                row_data["rfc_encontrado"],
                                row_data["confidence_score"],
                                row_data.get("source_page_first"),
                                row_data.get("movement_hash"),
                            ),
                        )
                    else:
                        conn.execute(
                            """
                            INSERT INTO bank_movements (issuer_id, statement_file_id, fecha, descripcion, deposito, retiro, saldo, tipo, categoria, metodo_hint, contraparte_hint, rfc_encontrado, confidence_score, source_page_first)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                row_data["issuer_id"],
                                row_data["statement_file_id"] or str(statement_id),
                                row_data["fecha"],
                                row_data["descripcion"],
                                row_data["deposito"],
                                row_data["retiro"],
                                row_data["saldo"],
                                row_data["tipo"],
                                row_data["categoria"],
                                row_data["metodo_hint"],
                                row_data["contraparte_hint"],
                                row_data["rfc_encontrado"],
                                row_data["confidence_score"],
                                row_data.get("source_page_first"),
                            ),
                        )
                inserted_count += 1
        # Balance mismatch detection
        _check_balance_mismatch(conn, statement_id, metadata)
        conn.commit()
        return {
            "ok": True,
            "statement_id": statement_id,
            "inserted_count": inserted_count,
            "duplicate_statement": False,
            "duplicate_movements_count": duplicate_movements_count,
            "skipped_count": duplicate_movements_count,
            "period_month": period_month,
        }
    except Exception as e:
        logger.exception("commit_preview_to_db: error issuer=%s", issuer_id)
        try:
            conn.rollback()
        except Exception:
            pass
        return {"ok": False, "status": "error", "rejection_reason": str(e)}
    finally:
        try:
            conn.close()
        except Exception:
            pass
