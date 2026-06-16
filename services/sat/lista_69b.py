"""Download and parse the SAT public list of contribuyentes 69-B (EFOS).

The Lista 69-B contains RFCs of taxpayers with presumed or confirmed
simulated operations. Invoicing to these RFCs should be blocked or warned.
"""
import csv
import io
import logging
from typing import Optional

from database import db, db_rows

logger = logging.getLogger(__name__)

# Public URL for the SAT 69-B list (may change; fetch failures are non-fatal)
LISTA_URL = "http://omawww.sat.gob.mx/cifras_sat/Documents/Listado_Completo_69-B.csv"


def fetch_and_update_lista() -> dict:
    """Download the 69-B list from SAT and upsert into sat_lista_69b.

    Returns dict with count of records processed and any errors.
    """
    try:
        import httpx
    except ImportError:
        logger.warning("httpx not installed, skipping 69-B fetch")
        return {"status": "skipped", "reason": "httpx not installed"}

    try:
        with httpx.Client(timeout=60.0, follow_redirects=True) as client:
            resp = client.get(LISTA_URL)
        if resp.status_code != 200:
            return {"status": "error", "reason": f"SAT returned {resp.status_code}"}

        text = resp.text
        reader = csv.DictReader(io.StringIO(text))
        records = []
        for row in reader:
            rfc = (row.get("RFC") or row.get("rfc") or "").strip().upper()
            if not rfc or len(rfc) < 12:
                continue
            nombre = row.get("Nombre del Contribuyente") or row.get("nombre") or ""
            situacion = row.get("Supuesto") or row.get("situacion") or ""
            records.append((rfc, nombre.strip(), situacion.strip()))

        if not records:
            return {"status": "error", "reason": "No records parsed from CSV"}

        conn = db()
        try:
            for rfc, nombre, situacion in records:
                conn.execute(
                    """INSERT INTO sat_lista_69b (rfc, nombre, situacion, refreshed_at)
                       VALUES (?, ?, ?, datetime('now'))
                       ON CONFLICT(rfc) DO UPDATE SET
                         nombre = excluded.nombre,
                         situacion = excluded.situacion,
                         refreshed_at = excluded.refreshed_at""",
                    (rfc, nombre, situacion),
                )
            conn.commit()
        finally:
            conn.close()

        return {"status": "ok", "count": len(records)}
    except Exception as exc:
        logger.warning("69-B fetch failed: %s", exc)
        return {"status": "error", "reason": str(exc)}


def check_rfc_69b(rfc: str) -> Optional[dict]:
    """Check if an RFC is in the 69-B list.

    Args:
        rfc: RFC to check (case-insensitive).

    Returns:
        Dict with rfc, nombre, situacion if found, None otherwise.
    """
    if not rfc:
        return None
    rows = db_rows(
        "SELECT rfc, nombre, situacion FROM sat_lista_69b WHERE rfc = ? LIMIT 1",
        (rfc.strip().upper(),),
    )
    return rows[0] if rows else None


def is_rfc_blocked(rfc: str) -> bool:
    """Check if an RFC should be blocked from invoicing.

    Definitivo and Sentencia Favorable are hard blocks.
    Presunto is a warning only (returns False).
    """
    result = check_rfc_69b(rfc)
    if not result:
        return False
    sit = (result.get("situacion") or "").lower()
    return sit in ("definitivo", "sentencia favorable")


def is_rfc_warned(rfc: str) -> bool:
    """Check if an RFC has a warning (Presunto) in 69-B list."""
    result = check_rfc_69b(rfc)
    if not result:
        return False
    sit = (result.get("situacion") or "").lower()
    return sit == "presunto"
