"""Job handler: provision a Facturapi organization for an issuer.

Runs out-of-band so signup is not coupled to Facturapi's availability. The
handler is idempotent — if facturapi_org_id is already set on the issuer, it
short-circuits without an HTTP call.
"""
from __future__ import annotations

import logging
from typing import Any

from database import db
from services.facturapi import orgs as fpi_orgs

logger = logging.getLogger(__name__)


def _read_issuer(issuer_id: int) -> dict | None:
    conn = db()
    try:
        row = conn.execute(
            """SELECT id, razon_social, rfc, regimen_fiscal, facturapi_org_id
               FROM issuers WHERE id = ? LIMIT 1""",
            (issuer_id,),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    return dict(row) if hasattr(row, "keys") else dict(zip(row.keys(), row))


def _save_org_id(issuer_id: int, org_id: str) -> None:
    conn = db()
    try:
        conn.execute(
            """UPDATE issuers
               SET facturapi_org_id = ?,
                   facturapi_provisioned_at = datetime('now'),
                   updated_at = datetime('now')
               WHERE id = ?""",
            (org_id, issuer_id),
        )
        conn.commit()
    finally:
        conn.close()


def handle_facturapi_provision_org(job: dict, _ctx: Any) -> dict:
    """Create the Facturapi organization for the issuer pointed to by the job.

    The job's issuer_id determines which tenant to provision.
    Returns a dict summarizing what happened. Raises on transient errors so the
    worker retries per max_attempts.
    """
    issuer_id = int(job.get("issuer_id") or 0)
    if issuer_id <= 0:
        return {"skipped": True, "reason": "no issuer_id"}

    issuer = _read_issuer(issuer_id)
    if not issuer:
        return {"skipped": True, "reason": "issuer not found", "issuer_id": issuer_id}

    if issuer.get("facturapi_org_id"):
        return {"skipped": True, "reason": "already provisioned", "org_id": issuer["facturapi_org_id"]}

    legal_name = (issuer.get("razon_social") or "").strip() or f"Tenant {issuer_id}"

    try:
        result = fpi_orgs.create_organization(legal_name=legal_name)
    except fpi_orgs.FacturapiOrgsError as e:
        logger.warning("facturapi_provision_org issuer=%s failed: %s", issuer_id, e)
        # Re-raise so the worker counts the attempt; 4xx are retried up to
        # max_attempts, after which the job stays in 'failed' for manual review.
        raise

    org_id = str(result.get("id") or "").strip()
    if not org_id:
        raise fpi_orgs.FacturapiOrgsError(0, f"create_organization returned no id: {result!r}")

    _save_org_id(issuer_id, org_id)
    logger.info("facturapi_provision_org issuer=%s org_id=%s", issuer_id, org_id)
    return {"org_id": org_id, "issuer_id": issuer_id}
