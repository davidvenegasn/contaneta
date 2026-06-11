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
            """SELECT id, razon_social, rfc, regimen_fiscal, facturapi_org_id, fiscal_zip
               FROM issuers WHERE id = ? LIMIT 1""",
            (issuer_id,),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    return dict(row) if hasattr(row, "keys") else dict(zip(row.keys(), row))


def ensure_live_ready(issuer_id: int) -> dict:
    """Check if issuer's Facturapi org is production-ready and cache the LIVE
    API key if so.

    Called after any onboarding milestone (legal info save, FIEL sign, CSD
    upload) — auto-promotes the org to LIVE as soon as Facturapi reports
    `is_production_ready: True` and `pending_steps: []`.

    Idempotent: if live key is already cached and fresh, returns immediately.

    Returns dict with keys:
      - `live_ready` (bool): is the org production-ready in Facturapi
      - `live_key_cached` (bool): did we (just) save the live key to DB
      - `pending_steps` (list[str]): remaining steps (if any)
    """
    issuer = _read_issuer(issuer_id)
    if not issuer:
        return {"live_ready": False, "live_key_cached": False, "error": "issuer not found"}
    org_id = (issuer.get("facturapi_org_id") or "").strip()
    if not org_id:
        return {"live_ready": False, "live_key_cached": False, "error": "no org_id"}

    try:
        org_data = fpi_orgs.get_organization(org_id)
    except Exception as e:
        logger.warning("ensure_live_ready: get_organization failed issuer=%s: %s", issuer_id, e)
        return {"live_ready": False, "live_key_cached": False, "error": "facturapi_unreachable"}

    pending = [s.get("type", "") for s in (org_data.get("pending_steps") or []) if isinstance(s, dict)]
    is_ready = bool(org_data.get("is_production_ready")) and not pending

    if not is_ready:
        return {"live_ready": False, "live_key_cached": False, "pending_steps": pending}

    # Org is ready. Fetch + cache test/live keys if not already done.
    try:
        from services.facturapi.api_keys import save_org_keys
        from database import db
        conn = db()
        try:
            row = conn.execute(
                "SELECT facturapi_live_key_encrypted FROM issuers WHERE id=?",
                (issuer_id,),
            ).fetchone()
            already_have_live = bool(row and (dict(row).get("facturapi_live_key_encrypted") or "").strip())
        finally:
            conn.close()
        if already_have_live:
            return {"live_ready": True, "live_key_cached": False, "pending_steps": []}
        test_key = fpi_orgs.get_org_api_key(org_id, mode="test")
        # `renew` returns the full live key string. `get` for live only returns
        # the first 12 chars (Facturapi only reveals full key once on creation).
        live_key = fpi_orgs.renew_org_api_key(org_id, mode="live")
        save_org_keys(
            issuer_id,
            test_key=test_key if isinstance(test_key, str) else None,
            live_key=live_key if isinstance(live_key, str) else None,
        )
        logger.info("Cached LIVE key for issuer=%s org=%s", issuer_id, org_id)
        return {"live_ready": True, "live_key_cached": True, "pending_steps": []}
    except Exception as e:
        logger.warning("ensure_live_ready: cache keys failed issuer=%s: %s", issuer_id, e)
        return {"live_ready": True, "live_key_cached": False, "error": str(e)}


def push_legal_info_to_facturapi(issuer_id: int) -> dict:
    """Sync the issuer's legal data (razon_social, regimen_fiscal, fiscal_zip)
    from our DB to Facturapi's org. Best-effort: skips fields that are missing
    in DB. Without complete legal info, Facturapi keeps the org in "test" mode
    with generic RFC — this call moves it toward "live-ready".

    Idempotent. Safe to call repeatedly (e.g. on every settings save).

    Returns the API response (or {} if no data to send / no org_id).
    """
    issuer = _read_issuer(issuer_id)
    if not issuer:
        return {}
    org_id = (issuer.get("facturapi_org_id") or "").strip()
    if not org_id:
        return {}
    legal_name = (issuer.get("razon_social") or "").strip()
    tax_system = (issuer.get("regimen_fiscal") or "").strip()
    zip_code = (issuer.get("fiscal_zip") or "").strip()
    if not (legal_name or tax_system or zip_code):
        return {}
    try:
        result = fpi_orgs.update_legal_info(
            org_id,
            legal_name=legal_name or None,
            tax_system=tax_system or None,
            zip_code=zip_code or None,
        )
        logger.info(
            "Pushed legal_info issuer=%s org=%s legal_name=%s tax=%s zip=%s",
            issuer_id, org_id, bool(legal_name), bool(tax_system), bool(zip_code),
        )
        return result
    except fpi_orgs.FacturapiOrgsError as e:
        logger.warning(
            "push_legal_info issuer=%s org=%s failed: %s", issuer_id, org_id, e
        )
        return {}


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


def ensure_provisioned(issuer_id: int) -> dict:
    """Synchronously ensure issuer has a Facturapi organization.

    Idempotent: if `facturapi_org_id` already exists, returns it immediately
    (no HTTP call). Otherwise creates the org via Facturapi API and saves to DB.

    Use from request handlers (signup, settings page load) to make provisioning
    feel automatic from the user's perspective — no worker required.

    Returns:
        Dict with keys: `org_id`, `already_provisioned` (bool), `issuer_id`.

    Raises:
        FacturapiOrgsError: if Facturapi is unreachable or rejects the request.
        ValueError: if issuer doesn't exist.
    """
    issuer_id = int(issuer_id)
    if issuer_id <= 0:
        raise ValueError(f"invalid issuer_id: {issuer_id}")

    issuer = _read_issuer(issuer_id)
    if not issuer:
        raise ValueError(f"issuer {issuer_id} not found")

    existing = (issuer.get("facturapi_org_id") or "").strip()
    if existing:
        return {"org_id": existing, "already_provisioned": True, "issuer_id": issuer_id}

    legal_name = (issuer.get("razon_social") or "").strip() or f"Tenant {issuer_id}"
    result = fpi_orgs.create_organization(legal_name=legal_name)

    org_id = str(result.get("id") or "").strip()
    if not org_id:
        raise fpi_orgs.FacturapiOrgsError(0, f"create_organization returned no id: {result!r}")

    _save_org_id(issuer_id, org_id)

    # Push legal info to Facturapi immediately: razon_social, regimen_fiscal,
    # fiscal_zip (if we have them). Without this, Facturapi keeps the org in
    # test mode with generic RFC. Best-effort: failure here doesn't block the
    # provision (the user can re-trigger later from /settings).
    try:
        push_legal_info_to_facturapi(issuer_id)
    except Exception as e:
        logger.warning("Initial legal_info push failed for issuer=%s: %s", issuer_id, e)

    # Pre-fetch the org's test API key so emission is ready immediately.
    try:
        from services.facturapi.api_keys import save_org_keys
        test_key = fpi_orgs.get_org_api_key(org_id, mode="test")
        if test_key:
            save_org_keys(issuer_id, test_key=test_key)
            logger.info("Pre-fetched test API key for issuer=%s org=%s", issuer_id, org_id)
    except Exception as e:
        logger.warning("Could not pre-fetch test API key for org %s: %s", org_id, e)

    logger.info("ensure_provisioned issuer=%s org_id=%s", issuer_id, org_id)
    return {"org_id": org_id, "already_provisioned": False, "issuer_id": issuer_id}


def handle_facturapi_provision_org(job: dict, _ctx: Any) -> dict:
    """Job handler wrapper around ensure_provisioned().

    Kept as fallback for cases where signup-time provisioning fails (Facturapi
    down, network blip) — the job retries up to max_attempts.
    """
    issuer_id = int(job.get("issuer_id") or 0)
    if issuer_id <= 0:
        return {"skipped": True, "reason": "no issuer_id"}

    try:
        return ensure_provisioned(issuer_id)
    except ValueError as e:
        return {"skipped": True, "reason": str(e), "issuer_id": issuer_id}
    except fpi_orgs.FacturapiOrgsError as e:
        logger.warning("facturapi_provision_org issuer=%s failed: %s", issuer_id, e)
        raise  # Re-raise so worker retries
