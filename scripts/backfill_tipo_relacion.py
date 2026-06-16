"""Backfill tipo_relacion + related_uuids on existing Egreso CFDI.

Reads XML files for all Egresos that have xml_path set but tipo_relacion IS NULL.
Extracts CfdiRelacionados node and updates the sat_cfdi table.
Idempotent — safe to run multiple times.
"""
import json
import logging
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database import db

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(message)s")

NS_CFDI4 = "http://www.sat.gob.mx/cfd/4"
NS_CFDI3 = "http://www.sat.gob.mx/cfd/3"


def extract(xml_path: Path) -> tuple:
    """Extract TipoRelacion and related UUIDs from a CFDI XML file."""
    tree = ET.parse(str(xml_path))
    root = tree.getroot()
    # Try CFDI 4.0 and 3.3 namespaces
    for ns_uri in (NS_CFDI4, NS_CFDI3):
        rel = root.find(f"{{{ns_uri}}}CfdiRelacionados")
        if rel is not None:
            tipo = rel.get("TipoRelacion")
            uuids = []
            for child in rel:
                u = child.get("UUID", "")
                if u:
                    uuids.append(u.lower())
            return tipo, uuids
    return None, []


def main():
    """Run backfill for all Egresos with missing tipo_relacion."""
    conn = db()
    rows = conn.execute(
        """SELECT id, xml_path FROM sat_cfdi
           WHERE tipo_comprobante = 'E'
             AND tipo_relacion IS NULL
             AND xml_path IS NOT NULL
             AND xml_path != ''"""
    ).fetchall()

    if not rows:
        print("No Egresos to backfill.")
        conn.close()
        return

    print(f"Processing {len(rows)} Egresos...")
    n_ok = n_err = n_skip = 0
    base = Path(__file__).resolve().parent.parent

    for r in rows:
        raw_path = r["xml_path"]
        # Handle both absolute and relative paths
        p = Path(raw_path)
        if not p.is_absolute():
            p = base / raw_path
        if not p.exists():
            n_skip += 1
            continue
        try:
            tipo, uuids = extract(p)
            conn.execute(
                "UPDATE sat_cfdi SET tipo_relacion = ?, related_uuids = ? WHERE id = ?",
                (tipo, json.dumps(uuids) if uuids else None, r["id"]),
            )
            n_ok += 1
        except Exception as e:
            logger.warning("backfill failed id=%s: %s", r["id"], e)
            n_err += 1

    conn.commit()
    conn.close()
    print(f"OK: {n_ok}  errors: {n_err}  missing-xml: {n_skip}")


if __name__ == "__main__":
    main()
