"""Top-level API for declaration upload + processing."""
import json
import logging
from typing import Optional

from database import db, db_rows
from services.declarations import parser, rfc_extractor, storage

logger = logging.getLogger(__name__)


def process_uploaded_pdf(
    *,
    pdf_bytes: bytes,
    uploaded_by_user_id: int,
    filename: str,
    target_issuer_id: Optional[int] = None,
) -> dict:
    """Parse a single PDF and persist the declaration row.

    If target_issuer_id is provided, use it directly.
    Otherwise, try to auto-detect from the RFC inside the PDF.

    Returns dict with declaration_id, status, parse_confidence, matched_issuer_id.
    """
    extracted = parser.extract_from_pdf(pdf_bytes)
    rfc_in_pdf = rfc_extractor.find_rfc_in_pdf(extracted.get("raw_text", ""))

    issuer_id = target_issuer_id
    if not issuer_id and rfc_in_pdf:
        rows = db_rows(
            "SELECT id FROM issuers WHERE UPPER(rfc) = UPPER(?) AND active = 1 LIMIT 1",
            (rfc_in_pdf,),
        )
        if rows:
            issuer_id = rows[0]["id"]

    if not issuer_id:
        return {
            "status": "rejected",
            "reason": "no_matching_issuer",
            "rfc_in_pdf": rfc_in_pdf,
            "parse_confidence": extracted.get("parse_confidence", 0),
        }

    rel_path, sha = storage.save_pdf_for_issuer(
        issuer_id, pdf_bytes, extracted.get("periodo_ym")
    )

    # Check duplicate by SHA
    dup = db_rows("SELECT id FROM declarations WHERE pdf_sha256 = ? LIMIT 1", (sha,))
    if dup:
        return {
            "status": "duplicate",
            "declaration_id": dup[0]["id"],
            "reason": "Same PDF already uploaded",
        }

    confidence = extracted.get("parse_confidence", 0)
    auto_status = "validated" if confidence >= 0.7 else "pending_review"

    conn = db()
    try:
        cur = conn.execute(
            """INSERT INTO declarations (
                issuer_id, uploaded_by_user_id, tipo, periodo_ym, fecha_presentacion,
                fecha_vencimiento, saldo_a_cargo, saldo_a_favor, total_a_pagar,
                linea_captura, folio_acuse, pdf_path, pdf_sha256,
                parsed_at, parse_confidence, parse_engine, raw_extracted_json, status
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?, datetime('now'), ?, 'pdfplumber-regex', ?, ?)""",
            (
                issuer_id, uploaded_by_user_id,
                extracted.get("tipo") or "desconocido",
                extracted.get("periodo_ym"),
                extracted.get("fecha_presentacion"),
                extracted.get("fecha_vencimiento"),
                extracted.get("saldo_a_cargo"),
                extracted.get("saldo_a_favor"),
                extracted.get("total_a_pagar"),
                extracted.get("linea_captura"),
                extracted.get("folio_acuse"),
                rel_path, sha,
                confidence,
                json.dumps(extracted, default=str),
                auto_status,
            ),
        )
        declaration_id = cur.lastrowid
        conn.commit()
    finally:
        conn.close()

    return {
        "status": "saved",
        "declaration_id": declaration_id,
        "matched_issuer_id": issuer_id,
        "rfc_in_pdf": rfc_in_pdf,
        "parse_confidence": confidence,
        "needs_review": confidence < 0.7,
    }


def get_declarations_for_issuer(
    issuer_id: int, *, status: Optional[str] = None, limit: int = 50
) -> list[dict]:
    """Get declarations for an issuer, newest first."""
    sql = "SELECT * FROM declarations WHERE issuer_id = ?"
    params: list = [issuer_id]
    if status:
        sql += " AND status = ?"
        params.append(status)
    sql += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    return db_rows(sql, tuple(params))


def get_declaration_by_id(declaration_id: int, issuer_id: int) -> Optional[dict]:
    """Get a single declaration scoped to issuer."""
    rows = db_rows(
        "SELECT * FROM declarations WHERE id = ? AND issuer_id = ?",
        (declaration_id, issuer_id),
    )
    return rows[0] if rows else None


def validate_declaration(declaration_id: int, issuer_id: int, updates: dict) -> bool:
    """Validate/update a declaration after manual review."""
    allowed = {"tipo", "periodo_ym", "saldo_a_cargo", "saldo_a_favor",
               "total_a_pagar", "linea_captura", "folio_acuse", "fecha_presentacion",
               "fecha_vencimiento"}
    sets = ["status = 'validated'", "updated_at = datetime('now')"]
    params = []
    for k, v in updates.items():
        if k in allowed:
            sets.append(f"{k} = ?")
            params.append(v)
    params.extend([declaration_id, issuer_id])
    conn = db()
    try:
        conn.execute(
            f"UPDATE declarations SET {', '.join(sets)} WHERE id = ? AND issuer_id = ?",
            tuple(params),
        )
        conn.commit()
    finally:
        conn.close()
    return True


def get_declarations_uploaded_by(user_id: int, limit: int = 100) -> list[dict]:
    """Get declarations uploaded by a specific user (for accountant view)."""
    return db_rows(
        """SELECT d.*, i.rfc AS issuer_rfc, i.razon_social AS issuer_name
           FROM declarations d
           JOIN issuers i ON i.id = d.issuer_id
           WHERE d.uploaded_by_user_id = ?
           ORDER BY d.created_at DESC LIMIT ?""",
        (user_id, limit),
    )
