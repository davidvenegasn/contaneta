"""Facturapi organizations API client (multi-tenant SaaS).

Auth model (confirmed with Facturapi support):
  - One master User Key authenticates ALL calls.
  - Per-org scoping is done by including organization_id in the URL.

These calls are made from the job worker (org creation) or from authenticated
portal endpoints (CSD upload). Never call directly from request hot path —
Facturapi can be slow or rate-limit.
"""
from __future__ import annotations

import logging
import os
from typing import BinaryIO

import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://www.facturapi.io/v2"
DEFAULT_TIMEOUT = 60


class FacturapiOrgsError(Exception):
    """Raised when a Facturapi orgs API call returns non-2xx."""
    def __init__(self, status: int, message: str):
        super().__init__(f"Facturapi orgs {status}: {message}")
        self.status = status
        self.body = message


def _user_key() -> str:
    key = (os.getenv("FACTURAPI_SECRET_KEY") or "").strip()
    if not key:
        raise FacturapiOrgsError(0, "FACTURAPI_SECRET_KEY not set in env")
    return key


def _headers_json() -> dict:
    return {
        "Authorization": f"Bearer {_user_key()}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _headers_multipart() -> dict:
    # requests sets Content-Type with boundary automatically when 'files' is passed.
    return {
        "Authorization": f"Bearer {_user_key()}",
        "Accept": "application/json",
    }


def create_organization(legal_name: str) -> dict:
    """POST /v2/organizations — create a new organization.

    Per Facturapi: RFC is set when the CSD is uploaded, so we only send `name`
    here. Other fiscal info (legal_name, tax_system, address) is set via
    update_legal_info once the tenant fills it in.

    Returns the org object including `id`.
    """
    if not legal_name or not str(legal_name).strip():
        raise FacturapiOrgsError(0, "legal_name required to create organization")
    payload = {"name": str(legal_name).strip()[:200]}
    r = requests.post(
        f"{BASE_URL}/organizations",
        json=payload,
        headers=_headers_json(),
        timeout=DEFAULT_TIMEOUT,
    )
    if r.status_code >= 400:
        raise FacturapiOrgsError(r.status_code, r.text[:500])
    return r.json()


def update_legal_info(
    org_id: str,
    *,
    legal_name: str | None = None,
    tax_system: str | None = None,
    zip_code: str | None = None,
) -> dict:
    """PUT /v2/organizations/{id}/legal — update fiscal data after CSD sets RFC."""
    if not org_id:
        raise FacturapiOrgsError(0, "org_id required")
    body: dict = {}
    if legal_name:
        body["legal_name"] = str(legal_name).strip()[:200]
    if tax_system:
        body["tax_system"] = str(tax_system).strip()
    if zip_code:
        body["address"] = {"zip": str(zip_code).strip()[:5]}
    if not body:
        return {}
    r = requests.put(
        f"{BASE_URL}/organizations/{org_id}/legal",
        json=body,
        headers=_headers_json(),
        timeout=DEFAULT_TIMEOUT,
    )
    if r.status_code >= 400:
        raise FacturapiOrgsError(r.status_code, r.text[:500])
    return r.json()


def sign_manifesto(
    org_id: str,
    *,
    cer_bytes: bytes,
    key_bytes: bytes,
    password: str,
) -> dict:
    """PUT /v2/organizations/{id}/fiel — sign carta manifesto headlessly.

    Undocumented endpoint discovered empirically on 2026-06-06: Facturapi
    accepts the FIEL (.cer + .key + password) by API and signs the carta
    manifesto with the SAT on behalf of the org. No iframe, no redirect.
    Side effect: sets the org's tax_id to the FIEL's RFC.

    The endpoint is not in their public docs and Fin (their support AI) said
    no headless option existed — but PUT /organizations/{id}/fiel does exist
    and works with status 200 on a valid password.
    """
    if not org_id:
        raise FacturapiOrgsError(0, "org_id required")
    if not cer_bytes or not key_bytes:
        raise FacturapiOrgsError(0, "FIEL cer/key bytes required")
    if not password:
        raise FacturapiOrgsError(0, "FIEL password required")
    files = {
        "cer": ("fiel.cer", cer_bytes, "application/octet-stream"),
        "key": ("fiel.key", key_bytes, "application/octet-stream"),
    }
    data = {"password": password}
    r = requests.put(
        f"{BASE_URL}/organizations/{org_id}/fiel",
        files=files,
        data=data,
        headers=_headers_multipart(),
        timeout=120,
    )
    if r.status_code >= 400:
        raise FacturapiOrgsError(r.status_code, r.text[:500])
    return r.json()


def upload_csd(
    org_id: str,
    *,
    cer_bytes: bytes,
    key_bytes: bytes,
    password: str,
) -> dict:
    """PUT /v2/organizations/{id}/certificate — upload CSD (.cer + .key + password).

    Facturapi parses the certificate and sets the org's RFC from it. On success
    the org becomes ready to emit (after the manifesto is also signed).
    """
    if not org_id:
        raise FacturapiOrgsError(0, "org_id required")
    if not cer_bytes or not key_bytes:
        raise FacturapiOrgsError(0, "cer/key bytes required")
    if not password:
        raise FacturapiOrgsError(0, "password required")
    files = {
        "cer": ("certificate.cer", cer_bytes, "application/octet-stream"),
        "key": ("private.key", key_bytes, "application/octet-stream"),
    }
    data = {"password": password}
    r = requests.put(
        f"{BASE_URL}/organizations/{org_id}/certificate",
        files=files,
        data=data,
        headers=_headers_multipart(),
        timeout=120,
    )
    if r.status_code >= 400:
        raise FacturapiOrgsError(r.status_code, r.text[:500])
    return r.json()


def get_organization(org_id: str) -> dict:
    """GET /v2/organizations/{id} — read current state of an organization."""
    if not org_id:
        raise FacturapiOrgsError(0, "org_id required")
    r = requests.get(
        f"{BASE_URL}/organizations/{org_id}",
        headers=_headers_json(),
        timeout=DEFAULT_TIMEOUT,
    )
    if r.status_code >= 400:
        raise FacturapiOrgsError(r.status_code, r.text[:500])
    return r.json()
