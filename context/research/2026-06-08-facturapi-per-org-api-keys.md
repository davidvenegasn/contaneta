# Research: Per-Org API Key Authentication for Facturapi CFDI Emission

**Date:** 2026-06-08

## Problem

`facturapi_client.py` uses the User Secret Key (`sk_user_*` from env `FACTURAPI_SECRET_KEY`) for ALL API calls including emission. Facturapi requires the org's own API key (`sk_test_*` / `sk_live_*`) for POST /v2/invoices. Result: 401 Unauthorized on emission.

## Current Architecture

- `facturapi_client.py` — 4 functions: `create_invoice`, `download_invoice`, `cancel_invoice`, `get_invoice`. All use `_headers(org_id)` which sends User Key + `Facturapi-Organization` header.
- `services/facturapi/orgs.py` — Admin ops (create org, upload CSD, sign manifesto). Uses User Key correctly for these.
- `services/facturapi/provision.py` — Job handler creates org but does NOT fetch API key.

## Callers to Update

| Function | File | Line | Current Signature |
|----------|------|------|-------------------|
| `create_invoice` | `routers/invoicing.py` | 387 | `create_invoice(org_id, payload)` |
| `create_invoice` | `routers/api/invoices/quick_create.py` | 157 | `create_invoice(org_id, payload_fact)` |
| `download_invoice` | `routers/invoicing.py` | 229 | `download_invoice(org_id, invoice_id, fmt)` |
| `download_invoice` | `routers/api/invoices/_post_hooks.py` | 35 | `download_invoice(org_id, fact_id, "xml")` |
| `cancel_invoice` | `routers/api/invoices/cancel.py` | 65 | `facturapi_cancel(org_id, facturapi_id, motive)` |
| `cancel_invoice` | `routers/api/invoices/_post_hooks.py` | 144 | `facturapi_cancel(org_id, orig_facturapi_id, "01")` |

## Key Findings

- `encrypt_text(*, issuer_id, plaintext)` / `decrypt_text(*, issuer_id, token)` available in `services/sat/crypto_at_rest.py`
- Migration pattern: `_safe_add_column()` in `migrations_runner.py` (see 059-061)
- Facturapi endpoint: `GET /v2/organizations/{id}/apikeys/test` returns `{"value": "sk_test_..."}` (to be confirmed)
- All callers have `issuer` dict available with `issuer["id"]` and `issuer["facturapi_org_id"]`
