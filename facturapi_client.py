import os

import requests
from dotenv import load_dotenv

load_dotenv()

FACTURAPI_SECRET_KEY = os.getenv("FACTURAPI_SECRET_KEY", "")
BASE_URL = "https://www.facturapi.io/v2"

class FacturapiError(Exception):
    pass

def _headers(org_id: str) -> dict:
    # Facturapi usa Bearer token; la secret key define entorno y organización,
    # y además permite operar como multi-issuer con organization header (según tu configuración).
    # Si tu cuenta usa multi-issuer, normalmente se usa organization_id para seleccionar emisor.
    return {
        "Authorization": f"Bearer {FACTURAPI_SECRET_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Facturapi-Organization": org_id,  # si tu cuenta no requiere este header, lo ignorará
    }

def create_invoice(org_id: str, payload: dict) -> dict:
    r = requests.post(f"{BASE_URL}/invoices", json=payload, headers=_headers(org_id), timeout=60)
    if r.status_code >= 400:
        raise FacturapiError(f"Facturapi error {r.status_code}: {r.text}")
    return r.json()

def download_invoice(org_id: str, invoice_id: str, fmt: str) -> bytes:
    # Facturapi: GET /v2/invoices/{invoice_id}/{format} (xml|pdf|zip)  [oai_citation:12‡docs.facturapi.io](https://docs.facturapi.io/en/api/)
    r = requests.get(f"{BASE_URL}/invoices/{invoice_id}/{fmt}", headers=_headers(org_id), timeout=60)
    if r.status_code >= 400:
        raise FacturapiError(f"Facturapi download error {r.status_code}: {r.text}")
    return r.content

def cancel_invoice(org_id: str, invoice_id: str, motive: str) -> dict:
    """Cancel a stamped invoice via DELETE /v2/invoices/{id}?motive={code}.
    Returns the updated invoice object from FacturAPI."""
    r = requests.delete(
        f"{BASE_URL}/invoices/{invoice_id}",
        params={"motive": motive},
        headers=_headers(org_id),
        timeout=60,
    )
    if r.status_code >= 400:
        raise FacturapiError(f"Facturapi cancel error {r.status_code}: {r.text}")
    return r.json()

def get_invoice(org_id: str, invoice_id: str) -> dict:
    """Get invoice details via GET /v2/invoices/{id}."""
    r = requests.get(f"{BASE_URL}/invoices/{invoice_id}", headers=_headers(org_id), timeout=60)
    if r.status_code >= 400:
        raise FacturapiError(f"Facturapi get error {r.status_code}: {r.text}")
    return r.json()