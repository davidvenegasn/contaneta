# Programmer — Unified onboarding (FIEL + CSD → headless manifesto)

**Date**: 2026-06-06
**Status**: ✅ Implemented. Tests green: 865 passed (was 857).

## The breakthrough

Empirical endpoint discovery (`/tmp/fpi_endpoint_discovery.py`, since deleted):

`PUT /v2/organizations/{id}/fiel` exists in Facturapi's API but is **NOT documented publicly**. It accepts:
- `cer` (multipart file)
- `key` (multipart file)
- `password` (form field)

When called with a valid FIEL + correct password:
- Returns 200
- Sets the org's `tax_id` to the FIEL's RFC
- Signs the carta manifesto with the SAT
- Removes `manifiesto` from `pending_steps`

This unlocks **fully headless onboarding** — no iframe, no redirects, no Facturapi dashboard, no Certifica from the user's side. Verified end-to-end against the live test sandbox today with David's FIEL (VEND980918UR1).

Facturapi support (Fin) explicitly said no headless endpoint exists. The endpoint exists; it's just undocumented. Reported as fact, not opinion.

## What changed

### New
- `services/facturapi/orgs.py::sign_manifesto()` — wraps `PUT /v2/organizations/{id}/fiel`
- `routers/portal/facturapi_setup.py::portal_facturapi_onboard()` — `POST /portal/api/facturapi/onboard`, unified multipart endpoint that accepts FIEL + CSD together and orchestrates both Facturapi calls
- `routers/portal/facturapi_setup.py::portal_setup_credenciales()` — new unified onboarding page at `/portal/setup/credenciales`
- `templates/portal_onboarding.html` — single-screen UI with FIEL + CSD sections, real-time feedback, JS polling, progress states
- `migrations/060_issuers_onboarding_state.sql` — adds `csd_uploaded_at` and `onboarding_completed_at` columns to `issuers`
- 11 new tests across `test_facturapi_orgs.py` and `test_portal_manifesto.py`

### Modified
- `routers/portal/facturapi_setup.py` — `_read_issuer_facturapi_state()` now returns 5 lifecycle fields; status endpoint exposes them; old `/setup/manifiesto` URL now 302s to `/setup/credenciales` (backwards-compat); legacy `/upload-csd` endpoint now marks `csd_uploaded_at`
- `migrations_runner.py` — added handler for migration 060

### Deprecated (kept for compat)
- `templates/portal_manifesto.html` — old iframe-based template, still loaded by nothing but kept in tree (legacy URL redirects bypass it)
- `POST /portal/api/facturapi/upload-csd` — CSD-only endpoint, still works for backfill scenarios

## Endpoint contract

`POST /portal/api/facturapi/onboard` (multipart):

| Field | Type | Required |
|---|---|---|
| `fiel_cer` | file (.cer) | yes |
| `fiel_key` | file (.key) | yes |
| `fiel_password` | string | yes |
| `csd_cer` | file (.cer) | yes |
| `csd_key` | file (.key) | yes |
| `csd_password` | string | yes |
| `csrf_token` | string | yes |

Orchestration:
1. If manifesto not yet signed → call `sign_manifesto()` → on success stamp `manifest_signed_at`. On failure return 400/502 with `step: "manifesto"`.
2. If step 1 succeeded and CSD not yet uploaded → call `upload_csd()` → on success stamp `csd_uploaded_at`. On failure return 400/502 with `step: "csd"` and `manifest_signed: true` (so caller knows partial state).
3. If both done → stamp `onboarding_completed_at`.

Idempotent: re-submitting after partial success skips the steps already completed.

Errors surface Facturapi's error message verbatim so the user knows what to fix (wrong password, mismatched RFC, file not a CSD, etc.).

## Behavior of FIEL endpoint (observed)

- Status 200 + body = updated org JSON
- `tax_id` field changes from account placeholder (`XIA190128J61`) to FIEL's RFC (`VEND980918UR1`)
- `pending_steps` no longer includes `manifiesto` (only `legal` remains until fiscal data is filled)
- Side effect at SAT: manifesto signed and registered (verified separately by checking dashboard)

## Tests

```
tests/test_facturapi_orgs.py             10 passed (+3)
tests/test_portal_manifesto.py           14 passed (+5)
                                         ──
                                         24 passed in this feature
Full suite:                              865 passed, 4 skipped (was 857)
```

Zero regressions.

## Known limitations

1. **Endpoint is undocumented**. If Facturapi removes or changes it, this flow breaks. Mitigation: fall back to the iframe (legacy template still in tree). For paranoia, monitor `sign_manifesto` failure rate in production logs.
2. **No CIEC field** in the unified page. Konta asks for CIEC; ContaNeta currently does not — the existing SAT sync uses FIEL, not CIEC. If we add CIEC-based features later, the page needs a third section.
3. **CSD generation wizard** still pending — onboarding assumes the user already has a CSD. The despacho-led concierge flow we discussed is a separate iteration.
4. **No browser QA yet**. The endpoint is tested in isolation against mocked Facturapi. End-to-end browser test with real CSD + FIEL against live sandbox is the next user step.

## Manual smoke test instructions

1. Server should already be running (uvicorn --reload picks up changes)
2. Browser to `http://127.0.0.1:8000/portal/setup/credenciales` as the synthetic tenant
3. Fill in FIEL + CSD with real files
4. Click "Conectar y empezar a facturar"
5. Expected: success message, page reload, "Listo para facturar" state

If FIEL fails with "La contraseña es incorrecta" → password wrong.
If CSD fails → check that the `.cer` is a CSD (numeric serial) and matches the RFC the FIEL just set.
