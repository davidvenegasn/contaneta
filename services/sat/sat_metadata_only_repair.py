"""Detect and repair metadata-only CFDIs — those with metadata but no parsed XML."""
from __future__ import annotations

import logging
from typing import Optional

from database import db, db_execute, db_rows

logger = logging.getLogger(__name__)


def find_metadata_only_cfdis(issuer_id: int) -> list[dict]:
    """Find CFDIs that have metadata but no parsed XML.

    Returns list of {uuid, direction, fecha_emision}.
    """
    return db_rows(
        "SELECT uuid, direction, fecha_emision FROM sat_cfdi "
        "WHERE issuer_id = ? "
        "AND (xml_status IS NULL OR xml_status != 'parsed') "
        "AND uuid IS NOT NULL "
        "ORDER BY fecha_emision",
        (int(issuer_id),),
    )


def count_metadata_only(issuer_id: int) -> dict:
    """Return counts of metadata-only vs parsed CFDIs per direction.

    Returns {issued_parsed, issued_metadata_only, received_parsed, received_metadata_only}.
    """
    rows = db_rows(
        """SELECT direction,
                  SUM(CASE WHEN xml_status = 'parsed' THEN 1 ELSE 0 END) AS parsed,
                  SUM(CASE WHEN xml_status IS NULL OR xml_status != 'parsed' THEN 1 ELSE 0 END) AS metadata_only
           FROM sat_cfdi
           WHERE issuer_id = ? AND uuid IS NOT NULL
           GROUP BY direction""",
        (int(issuer_id),),
    )
    result = {
        "issued_parsed": 0, "issued_metadata_only": 0,
        "received_parsed": 0, "received_metadata_only": 0,
    }
    for r in rows:
        d = r["direction"]
        if d in ("issued", "received"):
            result[f"{d}_parsed"] = int(r["parsed"] or 0)
            result[f"{d}_metadata_only"] = int(r["metadata_only"] or 0)
    return result


def reset_checkpoint_for_repair(
    issuer_id: int,
    from_date: str = "2026-01-01 00:00:00",
) -> None:
    """Reset sat_sync_state checkpoint to force re-sync from from_date."""
    db_execute(
        "UPDATE sat_sync_state SET last_sync_from = ?, last_sync_to = ?, cooldown_until = NULL "
        "WHERE issuer_id = ?",
        (from_date, from_date, int(issuer_id)),
    )
    logger.info("Reset checkpoint for issuer=%s to %s", issuer_id, from_date)
