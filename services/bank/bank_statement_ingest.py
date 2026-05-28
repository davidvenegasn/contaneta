"""
Ingesta de estados de cuenta: inserción de bank_statements y bank_movements con dedupe.
Fase 2 del módulo Movimientos.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from database import db, has_column, table_exists
from services.bank.bank_ingest_helpers import (
    PARSER_NAME,
    PARSER_VERSION,
    STATUS_ACCEPTED,
    _check_balance_mismatch,
    _movement_dedup_hash,
    _movement_to_row,
    extract_statement_metadata,
    validate_statement_ownership,
)

logger = logging.getLogger(__name__)


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
                        row["issuer_id"], row["statement_file_id"], row["bank_statement_id"],
                        row["bank_account_id"], row["period_month"], row["movement_index"],
                        row["fecha"], row["descripcion"], row["raw_description"], row["normalized_description"],
                        row["deposito"], row["retiro"], row["saldo"], row["amount"], row["direction"],
                        row["tipo"], row["categoria"], row["metodo_hint"], row["contraparte_hint"],
                        row["rfc_encontrado"], row["counterparty_name_detected"], row["counterparty_rfc_detected"],
                        row["confidence_score"], row["duplicate_hash"], row["is_possible_duplicate"],
                        row["requires_cfdi"], row["cfdi_match_status"], row.get("movement_hash"), now,
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
                        row["issuer_id"], row["statement_file_id"], row["bank_statement_id"],
                        row["bank_account_id"], row["period_month"], row["movement_index"],
                        row["fecha"], row["descripcion"], row["raw_description"], row["normalized_description"],
                        row["deposito"], row["retiro"], row["saldo"], row["amount"], row["direction"],
                        row["tipo"], row["categoria"], row["metodo_hint"], row["contraparte_hint"],
                        row["rfc_encontrado"], row["counterparty_name_detected"], row["counterparty_rfc_detected"],
                        row["confidence_score"], row["duplicate_hash"], row["is_possible_duplicate"],
                        row["requires_cfdi"], row["cfdi_match_status"], now,
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
                        row["issuer_id"], row["statement_file_id"] or str(statement_id),
                        row["fecha"], row["descripcion"], row["deposito"], row["retiro"],
                        row["saldo"], row["tipo"], row["categoria"], row["metodo_hint"],
                        row["contraparte_hint"], row["rfc_encontrado"], row["confidence_score"],
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
