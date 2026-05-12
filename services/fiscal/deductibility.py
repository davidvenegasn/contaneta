"""Per-invoice CFDI deductibility logic with SAT-based auto-detection.

Auto-detect rules (high-confidence only; ambiguous cases default to 100%):
- Servicios profesionales/honorarios (clave SAT 80-84): 100% auto
- Restaurante (clave SAT 901015XX, concepto contiene 'restaurante'/'consumo alimentos'): 8.5% auto
- Gasolina (clave SAT 15101505) + forma_pago='01' (efectivo): 0% auto
- Resto: 100% default (no auto-detect)

IVA acreditable se calcula proporcionalmente al porcentaje deducible.

Referencias: LISR Art. 28, LIVA Art. 5-V.
"""

import logging

from database import db_execute, db_rows

logger = logging.getLogger(__name__)

# Auto-detect rules — keep conservative, only obvious cases
# Each: (rule_name, predicate_fn, percentage)
AUTO_RULES = [
    (
        "professional_services",
        lambda c: (c.get("clave_prod_serv") or "")[:2] in ("80", "81", "82", "83", "84"),
        100,
    ),
    (
        "restaurant",
        lambda c: (
            "RESTAUR" in (c.get("concepto") or "").upper()
            or (c.get("clave_prod_serv") or "").startswith("901015")
        ),
        8.5,
    ),
    (
        "fuel_cash",
        lambda c: (
            (c.get("clave_prod_serv") or "").startswith("151015")
            and (c.get("forma_pago") or "") == "01"
        ),
        0,
    ),
    (
        "office_supplies",
        lambda c: (c.get("clave_prod_serv") or "")[:2] == "44",
        100,
    ),
    (
        "software_saas",
        lambda c: (
            "SOFTWARE" in (c.get("concepto") or "").upper()
            or "SUSCRIP" in (c.get("concepto") or "").upper()
        ),
        100,
    ),
]


def detect_deductibility(cfdi_row: dict) -> tuple[float, str, str]:
    """Auto-detect deductibility from CFDI fields.

    Args:
        cfdi_row: dict with keys clave_prod_serv, concepto, forma_pago, uso_cfdi.

    Returns:
        (percentage, source, reason)
        source: 'auto' if a rule matched, 'default' otherwise.
    """
    for rule_name, predicate, pct in AUTO_RULES:
        try:
            if predicate(cfdi_row):
                return (pct, "auto", rule_name)
        except Exception:
            continue
    return (100.0, "default", "")


def get_deductibility(issuer_id: int, cfdi_uuid: str) -> dict:
    """Get current deductibility for a CFDI. If none stored, compute auto and persist."""
    rows = db_rows(
        "SELECT percentage, source, auto_reason FROM cfdi_deductibility "
        "WHERE issuer_id = ? AND cfdi_uuid = ? LIMIT 1",
        (issuer_id, cfdi_uuid),
    )
    if rows:
        return {
            "percentage": float(rows[0]["percentage"]),
            "source": rows[0]["source"],
            "auto_reason": rows[0].get("auto_reason"),
        }
    # Lookup the CFDI to auto-detect
    cfdi = db_rows(
        "SELECT clave_prod_serv, concepto, forma_pago, uso_cfdi "
        "FROM sat_cfdi WHERE issuer_id = ? AND uuid = ? LIMIT 1",
        (issuer_id, cfdi_uuid),
    )
    if not cfdi:
        return {"percentage": 100.0, "source": "default", "auto_reason": ""}
    pct, source, reason = detect_deductibility(dict(cfdi[0]))
    set_deductibility(issuer_id, cfdi_uuid, pct, source, reason)
    return {"percentage": pct, "source": source, "auto_reason": reason}


def set_deductibility(
    issuer_id: int,
    cfdi_uuid: str,
    percentage: float,
    source: str = "manual",
    reason: str = "",
) -> None:
    """Upsert deductibility for a CFDI."""
    if percentage < 0 or percentage > 100:
        raise ValueError("percentage must be 0-100")
    if source not in ("auto", "manual", "default"):
        raise ValueError("source must be auto, manual, or default")
    db_execute(
        """INSERT INTO cfdi_deductibility (cfdi_uuid, issuer_id, percentage, source, auto_reason, updated_at)
           VALUES (?, ?, ?, ?, ?, datetime('now'))
           ON CONFLICT(cfdi_uuid, issuer_id) DO UPDATE SET
             percentage = excluded.percentage,
             source = excluded.source,
             auto_reason = excluded.auto_reason,
             updated_at = datetime('now')""",
        (cfdi_uuid, issuer_id, percentage, source, reason),
    )


def get_deductibility_map(issuer_id: int, uuids: list[str]) -> dict[str, dict]:
    """Bulk fetch deductibility for many UUIDs at once.

    Returns:
        {uuid: {percentage, source, auto_reason}}
    """
    if not uuids:
        return {}
    placeholders = ",".join(["?"] * len(uuids))
    rows = db_rows(
        f"SELECT cfdi_uuid, percentage, source, auto_reason "
        f"FROM cfdi_deductibility WHERE issuer_id = ? AND cfdi_uuid IN ({placeholders})",
        tuple([issuer_id] + uuids),
    )
    return {
        r["cfdi_uuid"]: {
            "percentage": float(r["percentage"]),
            "source": r["source"],
            "auto_reason": r.get("auto_reason") or "",
        }
        for r in rows
    }
