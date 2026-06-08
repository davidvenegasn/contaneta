# Programmer Log: Per-Org API Key Auth for Facturapi Emission

**Date:** 2026-06-08

## Changes Made

### 1. Migration 062 — `issuers` table columns
- `facturapi_test_key_encrypted TEXT` — AES-GCM encrypted test API key
- `facturapi_live_key_encrypted TEXT` — AES-GCM encrypted live API key
- `facturapi_keys_fetched_at TEXT` — timestamp of last key fetch

### 2. `services/facturapi/orgs.py` — `get_org_api_key()`
- New function: `GET /v2/organizations/{id}/apikeys/{mode}`
- Handles both test (single dict) and live (list) response shapes

### 3. `services/facturapi/api_keys.py` — NEW
- `save_org_keys(issuer_id, *, test_key, live_key)` — encrypt + persist
- `load_org_key(issuer_id, *, mode)` — load + decrypt, returns None if absent

### 4. `facturapi_client.py` — Complete refactor
- All 4 functions now take `issuer_id: int` as first param
- `_resolve_org_key(issuer_id, org_id)` — DB cache → fetch → persist
- `_emit_headers(issuer_id, org_id)` — uses org's own key, NOT User Key
- User Key (`FACTURAPI_SECRET_KEY`) no longer used for emission

### 5. Callers updated (6 sites)
- `routers/invoicing.py:387` — create_invoice
- `routers/invoicing.py:229` — download_invoice
- `routers/api/invoices/quick_create.py:157` — create_invoice
- `routers/api/invoices/cancel.py:65` — cancel_invoice
- `routers/api/invoices/_post_hooks.py:35` — download_invoice
- `routers/api/invoices/_post_hooks.py:144` — cancel_invoice

### 6. `services/facturapi/provision.py` — Pre-fetch
- After `create_organization`, immediately fetches + persists test key
- Non-blocking: failure logs warning, emission can still fetch on demand

### 7. Tests
- `tests/test_facturapi_api_keys.py` — 5 tests (roundtrip, encryption, none, live, timestamp)
- `tests/test_facturapi_orgs.py` — 4 new tests (get test key, live list, 404, invalid mode)
- `tests/test_facturapi_provision.py` — Updated to verify pre-fetch behavior

## Test Results
- 874 passed, 0 failed, 4 skipped (3 pre-existing failures excluded — unrelated settings template)
