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


def _resolve_org_key(issuer_id: int, org_id: str) -> str:
    """Resolve the org's API key for emission: cached DB → fetch from Facturapi → persist.

    Args:
        issuer_id: Tenant ID (for encrypted key lookup).
        org_id: Facturapi organization ID.

    Returns:
        The org's API key (sk_test_... or sk_live_...).

    Raises:
        FacturapiError: If key cannot be resolved.
    """
    from services.facturapi.api_keys import load_org_key, save_org_keys

    key = load_org_key(issuer_id, mode="test")
    if key:
        return key

    # Fetch on first use, then cache
    try:
        from services.facturapi.orgs import get_org_api_key
        key = get_org_api_key(org_id, mode="test")
        if key:
            save_org_keys(issuer_id, test_key=key)
            return key
    except Exception as e:
        logger.warning("Failed to fetch org API key for issuer=%s org=%s: %s", issuer_id, org_id, e)

    raise FacturapiError("No se pudo obtener la API key de la organización para emitir")


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


def cancel_invoice(issuer_id: int, org_id: str, invoice_id: str, motive: str) -> dict:
    """Cancel a stamped invoice via DELETE /v2/invoices/{id}?motive={code}.

    Returns the updated invoice object from Facturapi.
    """
    r = requests.delete(
        f"{BASE_URL}/invoices/{invoice_id}",
        params={"motive": motive},
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
