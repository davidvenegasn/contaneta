"""
Commit bank statement preview to DB: persist movements without PDF.
Fase 3 del módulo Movimientos.
"""
from __future__ import annotations

import hashlib
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
    _statement_fingerprint_preview,
    extract_statement_metadata,
    validate_statement_ownership,
)
from services.bank.bank_preview_models import compute_dedupe_fingerprint

logger = logging.getLogger(__name__)


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
                                row_data["issuer_id"], row_data["statement_file_id"], row_data["bank_statement_id"],
                                row_data["bank_account_id"], row_data["period_month"], row_data["movement_index"],
                                row_data["fecha"], row_data["descripcion"], row_data["raw_description"],
                                row_data["normalized_description"], row_data["deposito"], row_data["retiro"],
                                row_data["saldo"], row_data["amount"], row_data["direction"],
                                row_data["tipo"], row_data["categoria"], row_data["metodo_hint"],
                                row_data["contraparte_hint"], row_data["rfc_encontrado"],
                                row_data["counterparty_name_detected"], row_data["counterparty_rfc_detected"],
                                row_data["confidence_score"], row_data["duplicate_hash"],
                                row_data["is_possible_duplicate"], row_data["requires_cfdi"],
                                row_data["cfdi_match_status"], row_data.get("movement_hash"), now,
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
                                row_data["issuer_id"], row_data["statement_file_id"], row_data["bank_statement_id"],
                                row_data["bank_account_id"], row_data["period_month"], row_data["movement_index"],
                                row_data["fecha"], row_data["descripcion"], row_data["raw_description"],
                                row_data["normalized_description"], row_data["deposito"], row_data["retiro"],
                                row_data["saldo"], row_data["amount"], row_data["direction"],
                                row_data["tipo"], row_data["categoria"], row_data["metodo_hint"],
                                row_data["contraparte_hint"], row_data["rfc_encontrado"],
                                row_data["counterparty_name_detected"], row_data["counterparty_rfc_detected"],
                                row_data["confidence_score"], row_data["duplicate_hash"],
                                row_data["is_possible_duplicate"], row_data["requires_cfdi"],
                                row_data["cfdi_match_status"], now,
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
                                row_data["issuer_id"], row_data["statement_file_id"] or str(statement_id),
                                row_data["fecha"], row_data["descripcion"], row_data["deposito"], row_data["retiro"],
                                row_data["saldo"], row_data["tipo"], row_data["categoria"], row_data["metodo_hint"],
                                row_data["contraparte_hint"], row_data["rfc_encontrado"], row_data["confidence_score"],
                                row_data.get("source_page_first"), row_data.get("movement_hash"),
                            ),
                        )
                    else:
                        conn.execute(
                            """
                            INSERT INTO bank_movements (issuer_id, statement_file_id, fecha, descripcion, deposito, retiro, saldo, tipo, categoria, metodo_hint, contraparte_hint, rfc_encontrado, confidence_score, source_page_first)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                row_data["issuer_id"], row_data["statement_file_id"] or str(statement_id),
                                row_data["fecha"], row_data["descripcion"], row_data["deposito"], row_data["retiro"],
                                row_data["saldo"], row_data["tipo"], row_data["categoria"], row_data["metodo_hint"],
                                row_data["contraparte_hint"], row_data["rfc_encontrado"], row_data["confidence_score"],
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
