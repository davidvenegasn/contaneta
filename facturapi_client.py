"""Facturapi HTTP client for CFDI emission, download, and cancellation.

Auth model:
  - Admin ops (create org, upload CSD, etc.) use the User Secret Key (sk_user_*)
    and live in services/facturapi/orgs.py — NOT here.
  - Emission ops (create/cancel/download invoice) use each org's own API key
    (sk_test_* or sk_live_*), stored encrypted in issuers table.
  - On first use, if no cached key exists, we fetch it from Facturapi and persist.
"""
from __future__ import annotations

import logging
import os

import requests
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

FACTURAPI_SECRET_KEY = os.getenv("FACTURAPI_SECRET_KEY", "")
BASE_URL = "https://www.facturapi.io/v2"


class FacturapiError(Exception):
    pass


def _emission_mode() -> str:
    """Read FACTURAPI_EMISSION_MODE from env. Defaults to 'test' for safety.

    Set to 'live' in .env to switch real CFDI emission against the SAT.
    Read at each call so .env changes via uvicorn --reload take effect.
    """
    mode = (os.getenv("FACTURAPI_EMISSION_MODE") or "test").strip().lower()
    return "live" if mode == "live" else "test"


def _resolve_org_key(issuer_id: int, org_id: str) -> str:
    """Resolve the org's API key for emission: cached DB → fetch from Facturapi → persist.

    Args:
        issuer_id: Tenant ID (for encrypted key lookup).
        org_id: Facturapi organization ID.

    Returns:
        The org's API key for the current FACTURAPI_EMISSION_MODE
        (sk_test_... or sk_live_...).

    Raises:
        FacturapiError: If key cannot be resolved.
    """
    from services.facturapi.api_keys import load_org_key, save_org_keys

    mode = _emission_mode()
    key = load_org_key(issuer_id, mode=mode)
    if key:
        return key

    # Fetch on first use, then cache
    try:
        from services.facturapi.orgs import get_org_api_key, renew_org_api_key, FacturapiOrgsError
        key = ""
        try:
            key = get_org_api_key(org_id, mode=mode)
        except FacturapiOrgsError as e:
            # Live mode may have NO key yet (empty list → 404 in our wrapper).
            # That's expected — Facturapi only creates the live key on demand.
            if mode == "live" and e.status == 404:
                logger.info("No live API key yet for org=%s, generating one (renew)…", org_id)
                key = renew_org_api_key(org_id, mode="live")
            else:
                raise
        if not key and mode == "live":
            key = renew_org_api_key(org_id, mode="live")
        if key:
            if mode == "live":
                save_org_keys(issuer_id, live_key=key)
            else:
                save_org_keys(issuer_id, test_key=key)
            return key
    except Exception as e:
        logger.warning("Failed to fetch %s org API key for issuer=%s org=%s: %s",
                       mode, issuer_id, org_id, e)

    raise FacturapiError(
        f"No se pudo obtener la API key {mode.upper()} de la organización para emitir"
    )


def _emit_headers(issuer_id: int, org_id: str) -> dict:
    """Headers for emission: uses the org's own API key, not the User Key."""
    key = _resolve_org_key(issuer_id, org_id)
    return {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _emit_headers_download(issuer_id: int, org_id: str) -> dict:
    """Headers for download (no Content-Type needed for GET)."""
    key = _resolve_org_key(issuer_id, org_id)
    return {
        "Authorization": f"Bearer {key}",
        "Accept": "application/json",
    }


def create_invoice(issuer_id: int, org_id: str, payload: dict) -> dict:
    """Create (emit) a CFDI via POST /v2/invoices using the org's API key."""
    r = requests.post(
        f"{BASE_URL}/invoices",
        json=payload,
        headers=_emit_headers(issuer_id, org_id),
        timeout=60,
    )
    if r.status_code >= 400:
        raise FacturapiError(f"Facturapi error {r.status_code}: {r.text}")
    return r.json()


def download_invoice(issuer_id: int, org_id: str, invoice_id: str, fmt: str) -> bytes:
    """Download invoice file via GET /v2/invoices/{id}/{format} (xml|pdf|zip)."""
    r = requests.get(
        f"{BASE_URL}/invoices/{invoice_id}/{fmt}",
        headers=_emit_headers_download(issuer_id, org_id),
        timeout=60,
    )
    if r.status_code >= 400:
        raise FacturapiError(f"Facturapi download error {r.status_code}: {r.text}")
    return r.content


def cancel_invoice(
    issuer_id: int,
    org_id: str,
    invoice_id: str,
    motive: str,
    substitution: str | None = None,
) -> dict:
    """Cancel a stamped invoice via DELETE /v2/invoices/{id}?motive={code}.

    Args:
        substitution: UUID of the substitute CFDI (required for motive 01).

    Returns the updated invoice object from Facturapi.
    """
    params = {"motive": motive}
    if substitution:
        params["substitution"] = substitution
    r = requests.delete(
        f"{BASE_URL}/invoices/{invoice_id}",
        params=params,
        headers=_emit_headers(issuer_id, org_id),
        timeout=60,
    )
    if r.status_code >= 400:
        raise FacturapiError(f"Facturapi cancel error {r.status_code}: {r.text}")
    return r.json()


def get_invoice(issuer_id: int, org_id: str, invoice_id: str) -> dict:
    """Get invoice details via GET /v2/invoices/{id}."""
    r = requests.get(
        f"{BASE_URL}/invoices/{invoice_id}",
        headers=_emit_headers(issuer_id, org_id),
        timeout=60,
    )
    if r.status_code >= 400:
        raise FacturapiError(f"Facturapi get error {r.status_code}: {r.text}")
    return r.json()
