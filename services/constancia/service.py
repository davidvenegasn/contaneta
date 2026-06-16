"""Constancia de Situación Fiscal — upload, parse, compare, persist."""
import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Optional

from database import db, db_rows
from services.constancia.parser import parse_constancia

logger = logging.getLogger(__name__)

STORAGE_DIR = Path(os.getenv("CONSTANCIA_STORAGE_DIR", "./storage/constancia"))


def process_constancia_upload(
    *,
    issuer_id: int,
    pdf_bytes: bytes,
    filename: str,
) -> dict:
    """Parse a constancia PDF, save it, and return extracted data + diff.

    Returns dict with:
        - extracted: parsed data from PDF
        - diff: list of {field, current, extracted} for mismatches
        - pdf_path: where the PDF was saved
        - sha256: hash of the PDF
    """
    # Parse PDF
    extracted = parse_constancia(pdf_bytes)
    if extracted.get("error"):
        return {"ok": False, "error": extracted["error"]}

    # Save PDF
    sha = hashlib.sha256(pdf_bytes).hexdigest()
    subdir = STORAGE_DIR / str(issuer_id)
    subdir.mkdir(parents=True, exist_ok=True)
    pdf_path = subdir / f"{sha[:16]}.pdf"
    if not pdf_path.exists():
        pdf_path.write_bytes(pdf_bytes)
    rel_path = str(pdf_path)

    # Compare with current issuer data
    issuer_rows = db_rows(
        "SELECT rfc, razon_social, regimen_fiscal, fiscal_zip FROM issuers WHERE id = ? LIMIT 1",
        (issuer_id,),
    )
    diff = []
    if issuer_rows:
        current = issuer_rows[0]
        _compare(diff, "RFC", current.get("rfc"), extracted.get("rfc"))
        _compare(diff, "Razón Social", current.get("razon_social"), extracted.get("razon_social"))
        _compare(diff, "Régimen Fiscal", current.get("regimen_fiscal"), extracted.get("regimen_fiscal"))
        _compare(diff, "Código Postal", current.get("fiscal_zip"), extracted.get("codigo_postal"))

    # Persist to issuers table
    conn = db()
    try:
        conn.execute(
            """UPDATE issuers
               SET constancia_pdf_path = ?,
                   constancia_uploaded_at = datetime('now'),
                   constancia_extracted_json = ?,
                   updated_at = datetime('now')
               WHERE id = ?""",
            (rel_path, json.dumps(extracted, ensure_ascii=False), issuer_id),
        )
        conn.commit()
    finally:
        conn.close()

    return {
        "ok": True,
        "extracted": extracted,
        "diff": diff,
        "pdf_path": rel_path,
        "sha256": sha,
        "verified": len(diff) == 0,
    }


def apply_extracted_data(issuer_id: int) -> dict:
    """Update issuer fields from the last constancia extraction.

    Only updates fields that were successfully extracted.
    """
    rows = db_rows(
        "SELECT constancia_extracted_json FROM issuers WHERE id = ? LIMIT 1",
        (issuer_id,),
    )
    if not rows or not rows[0].get("constancia_extracted_json"):
        return {"ok": False, "error": "No hay constancia procesada"}

    extracted = json.loads(rows[0]["constancia_extracted_json"])
    updates = []
    params = []

    if extracted.get("rfc"):
        updates.append("rfc = ?")
        params.append(extracted["rfc"])
    if extracted.get("razon_social"):
        updates.append("razon_social = ?")
        params.append(extracted["razon_social"])
    if extracted.get("regimen_fiscal"):
        updates.append("regimen_fiscal = ?")
        params.append(extracted["regimen_fiscal"])
    if extracted.get("codigo_postal"):
        updates.append("fiscal_zip = ?")
        params.append(extracted["codigo_postal"])

    if not updates:
        return {"ok": False, "error": "No hay datos para actualizar"}

    updates.append("updated_at = datetime('now')")
    params.append(issuer_id)

    conn = db()
    try:
        conn.execute(
            f"UPDATE issuers SET {', '.join(updates)} WHERE id = ?",
            params,
        )
        conn.commit()
    finally:
        conn.close()

    return {"ok": True, "fields_updated": len(updates) - 1}


def get_constancia_status(issuer_id: int) -> Optional[dict]:
    """Return constancia status for the issuer settings page."""
    rows = db_rows(
        """SELECT constancia_pdf_path, constancia_uploaded_at, constancia_extracted_json
           FROM issuers WHERE id = ? LIMIT 1""",
        (issuer_id,),
    )
    if not rows:
        return None
    r = rows[0]
    if not r.get("constancia_uploaded_at"):
        return None
    extracted = {}
    if r.get("constancia_extracted_json"):
        try:
            extracted = json.loads(r["constancia_extracted_json"])
        except (json.JSONDecodeError, TypeError):
            pass
    return {
        "uploaded_at": r["constancia_uploaded_at"],
        "pdf_path": r.get("constancia_pdf_path"),
        "extracted": extracted,
        "verified": extracted.get("confidence", 0) >= 0.75,
    }


def _compare(diff: list, field: str, current: Optional[str], extracted: Optional[str]) -> None:
    """Add to diff list if current and extracted values differ."""
    if not extracted:
        return
    c = (current or "").strip().upper()
    e = extracted.strip().upper()
    if c != e:
        diff.append({"field": field, "current": current or "", "extracted": extracted})
