"""Auto-update issuer fiscal data (RFC, razón social) from FIEL certificate.

After FIEL validation succeeds, compares the certificate's subject attributes
against the current issuer record and auto-fills placeholder values.  If the
current values look intentional (real RFC pattern) but differ from the cert,
a conflict notification is created instead of overwriting.
"""
from __future__ import annotations

import logging
import re

from database import db
from services.notifications import create_notification_if_missing, SEVERITY_WARNING
from services.sat.sat_credentials_secure import extract_fiel_subject

logger = logging.getLogger(__name__)

# Mexican RFC pattern: 3-4 letters + 6 digits + 3 alphanumeric checksum
_RFC_RE = re.compile(r"^[A-ZÑ&]{3,4}\d{6}[A-Z0-9]{3}$")


def _is_placeholder(value: str) -> bool:
    """Return True if value looks like a placeholder, not intentional data."""
    v = (value or "").strip()
    if not v:
        return True
    upper = v.upper()
    if upper in ("PENDIENTE", "PENDING", "N/A", "NA", "TBD"):
        return True
    if upper.startswith("PENDIENTE"):
        return True
    if "@" in v:
        return True
    # Very short strings (< 5 chars) that don't match RFC pattern
    if len(v) < 5 and not _RFC_RE.match(upper):
        return True
    return False


def _is_real_rfc(value: str) -> bool:
    """Return True if value matches the Mexican RFC pattern."""
    return bool(_RFC_RE.match((value or "").strip().upper()))


def maybe_update_issuer_from_fiel(issuer_id: int, *, dry_run: bool = False) -> dict:
    """Compare current issuer.rfc/razon_social against FIEL cert subject.

    If they differ AND current values look like placeholders ('PENDIENTE',
    empty, or obviously short like 'DAven'), auto-update.
    If current values look intentional (real RFC pattern), DO NOT overwrite.
    Just return a 'conflict' dict for UI to show a banner.

    Args:
        issuer_id: Tenant ID.
        dry_run: If True, don't write changes, just report what would happen.

    Returns:
        Dict with keys: updated (bool), conflicts (list), changes (dict),
        cert_rfc, cert_name.
    """
    result: dict = {
        "updated": False,
        "conflicts": [],
        "changes": {},
        "cert_rfc": "",
        "cert_name": "",
    }

    subject = extract_fiel_subject(issuer_id)
    if not subject:
        return result

    cert_rfc = (subject.get("rfc") or "").strip().upper()
    cert_name = (subject.get("nombre") or "").strip()
    result["cert_rfc"] = cert_rfc
    result["cert_name"] = cert_name

    if not cert_rfc:
        return result

    conn = db()
    try:
        row = conn.execute(
            "SELECT rfc, razon_social FROM issuers WHERE id = ?",
            (issuer_id,),
        ).fetchone()
        if not row:
            return result
        cur_rfc = (row["rfc"] if isinstance(row, dict) else row[0]) or ""
        cur_name = (row["razon_social"] if isinstance(row, dict) else row[1]) or ""
    finally:
        conn.close()

    updates: dict[str, str] = {}
    conflicts: list[dict] = []

    # RFC comparison
    if cur_rfc.strip().upper() == cert_rfc:
        pass  # Already matches
    elif _is_placeholder(cur_rfc):
        updates["rfc"] = cert_rfc
    elif _is_real_rfc(cur_rfc):
        conflicts.append({
            "field": "rfc",
            "current": cur_rfc,
            "from_cert": cert_rfc,
        })

    # Razón social comparison
    if cert_name:
        if cur_name.strip().upper() == cert_name.upper():
            pass  # Already matches
        elif _is_placeholder(cur_name):
            updates["razon_social"] = cert_name
        elif cur_name and len(cur_name.strip()) >= 5:
            conflicts.append({
                "field": "razon_social",
                "current": cur_name,
                "from_cert": cert_name,
            })

    result["changes"] = updates
    result["conflicts"] = conflicts

    if updates and not dry_run:
        conn = db()
        try:
            set_clauses = []
            params: list = []
            for field, value in updates.items():
                set_clauses.append(f"{field} = ?")
                params.append(value)
            set_clauses.append("updated_at = datetime('now')")
            params.append(issuer_id)
            conn.execute(
                f"UPDATE issuers SET {', '.join(set_clauses)} WHERE id = ?",
                tuple(params),
            )
            conn.commit()
            result["updated"] = True
            logger.info("Auto-updated issuer %s from FIEL cert: %s", issuer_id, updates)
        finally:
            conn.close()

    if conflicts and not dry_run:
        body_parts = []
        for c in conflicts:
            body_parts.append(f"{c['field']}: actual={c['current']}, FIEL={c['from_cert']}")
        create_notification_if_missing(
            issuer_id=issuer_id,
            type="fiel_rfc_conflict",
            title="Datos fiscales difieren de la FIEL",
            body=f"Los siguientes campos no coinciden con tu certificado FIEL: {'; '.join(body_parts)}. Verifica en Ajustes.",
            severity=SEVERITY_WARNING,
            action_url="/portal/config/sat",
            dedupe_parts=["fiel_rfc_conflict", str(issuer_id), cert_rfc],
        )

    return result
