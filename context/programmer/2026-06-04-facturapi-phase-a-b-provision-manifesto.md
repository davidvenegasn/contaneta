# Programmer — Phase A (auto-provisión) + Phase B (manifesto iframe)

**Date**: 2026-06-04
**Plan**: `context/plan/2026-06-01-facturapi-multi-tenant-integration.md`
**Status**: ✅ Both phases complete. Tests green: 857 (was 835 before, was 825 before Phase C).

## Phase A — Auto-provision Facturapi organization on tenant signup

### Files

NEW:
- `services/facturapi/orgs.py` — HTTP wrappers: `create_organization`, `update_legal_info`, `upload_csd`, `get_organization` + `FacturapiOrgsError`
- `services/facturapi/provision.py` — job handler `handle_facturapi_provision_org` (idempotent, fail-soft)
- `tests/test_facturapi_orgs.py` — 7 tests with mocked `requests`
- `tests/test_facturapi_provision.py` — 6 tests covering the handler + signup integration

MODIFIED:
- `worker.py` — registered the new handler in `_load_handlers()`
- `services/issuers.py:create_issuer_with_token` — after the existing INSERT, enqueues `facturapi_provision_org` job. Failure to enqueue does NOT break signup (logged, swallowed).

### Behavior

| Trigger | Effect |
|---|---|
| User signs up via `/signup` or `/auth/register` | Issuer row created → job `facturapi_provision_org` enqueued |
| Worker picks up the job | Reads issuer → if `facturapi_org_id` already set, skips. Otherwise calls `POST /v2/organizations` → on success, persists `facturapi_org_id` + `facturapi_provisioned_at` |
| Facturapi 4xx/5xx | Job re-raises → worker retries per `max_attempts=5` with backoff |
| `FACTURAPI_SECRET_KEY` not in env | `_user_key()` raises → job fails → stays in queue for next worker run after env fix |

Signup latency is unchanged (one extra `INSERT INTO jobs`, no HTTP call inline).

## Phase B — Embedded manifesto + CSD upload portal flow

### Files

NEW:
- `routers/portal/facturapi_setup.py` — 4 routes:
  - `GET /portal/setup/manifiesto` — page with 3 states (provisioning / ready / done)
  - `GET /portal/api/facturapi/status` — JSON poll endpoint
  - `POST /portal/api/facturapi/upload-csd` — multipart upload (CSRF protected, 50KB cap)
  - `POST /portal/api/facturapi/retry-provision` — re-enqueue provisioning job
- `templates/portal_manifesto.html` — 3-state UI with auto-polling + iframe
- `tests/test_portal_manifesto.py` — 9 tests across all 3 states + 3 upload scenarios

MODIFIED:
- `routers/portal/__init__.py` — registered `register_facturapi_setup_routes`

### Page states

State 1 — Org still provisioning (`facturapi_org_id` NULL):
- Shows "Preparando tu cuenta" card + manual retry button
- JS polls `/portal/api/facturapi/status` every 3s; reloads when provisioned

State 2 — Org ready, manifest not signed:
- "Paso 1 — Sube tu CSD" form: `.cer` + `.key` + password (CSRF protected)
- "Paso 2 — Firma tu carta manifiesto" with the Facturapi iframe (sandboxed)
- JS polls and reloads when webhook arrives setting `manifest_signed_at`

State 3 — Manifest signed:
- Success state with CTAs to home and emit-first-invoice

### Iframe URL

Hardcoded base: `https://www.facturapi.io/embedded/manifiesto?organization_id={org_id}`
Overridable via env `FACTURAPI_MANIFEST_IFRAME_URL` if Facturapi changes the URL or requires signed tokens. The exact params Facturapi expects are not in their public docs — this is my best guess. The first real test will tell us if the iframe loads correctly; if not, this is one line to change.

### CSD upload error surfacing

The endpoint catches `FacturapiOrgsError` and returns its message verbatim to the frontend. So when Facturapi rejects the upload with messages like:
- "El certificado no es un CSD"
- "Contraseña incorrecta"
- "El RFC del certificado no coincide"

…the tenant sees that exact message in the page (no opaque "Error 502"). This matches Facturapi's own UX, which is intentional — the tenant already knows how to react to those errors.

## Test summary

```
tests/test_facturapi_orgs.py        7 passed
tests/test_facturapi_provision.py   6 passed
tests/test_portal_manifesto.py      9 passed
                                   ──
                                   22 passed (new this commit)
Full suite:                        857 passed, 4 skipped (was 835)
```

Zero regressions. Existing emission flow unchanged.

## Open items / known limitations

1. **Manifest iframe URL params** — best guess until validated against a real Facturapi test event. Change `MANIFEST_IFRAME_BASE` in `routers/portal/facturapi_setup.py` or set `FACTURAPI_MANIFEST_IFRAME_URL` in `.env`.
2. **CSD upload does not parse the cert locally** — we send straight to Facturapi and let it validate. ContaNeta does not store the CSD bytes (different from FIEL which is stored encrypted for the PHP SAT sync).
3. **Sidebar nav entry** for "Configurar facturación" not added yet — would require modifying `templates/components/portal_sidebar_unified.html` with conditional rendering based on `manifest_signed_at`. Out of scope for this iteration; tenants navigate to `/portal/setup/manifiesto` directly. Add when product needs it.
4. **No auto-redirect** from `/portal/home` to setup when manifest unsigned. Same reason — keep this iteration narrow. Easy to add later.
5. **`update_legal_info`** is implemented but not yet called from anywhere. It'll be useful when we want to push the tenant's razón social / régimen / CP into Facturapi after CSD sets the RFC.

## What's needed from the user before going live

| Item | Status |
|---|---|
| `FACTURAPI_SECRET_KEY` in `.env` | ✅ confirmed sk_test_ |
| `FACTURAPI_WEBHOOK_SECRET` in `.env` | ⏳ depends on creating the webhook in Facturapi dashboard |
| Webhook endpoint registered in Facturapi dashboard | ⏳ pending |
| Public URL accessible by Facturapi (ngrok or deploy) | ⏳ pending — for webhook to actually reach |
| Real tenant test through the full flow | ⏳ this is the QA phase |

## How to test end-to-end (USER actions)

1. Run server: `./run_server.sh`
2. Run worker in another terminal: `python worker.py --loop`
3. Sign up a new tenant via `/signup`
4. Within seconds, the worker picks up `facturapi_provision_org` and populates `facturapi_org_id`
5. Visit `/portal/setup/manifiesto` → see "Paso 1 — Sube tu CSD"
6. Upload real CSD (`.cer` + `.key` + password) → if everything matches, Facturapi accepts → page reloads to show "Paso 2 — Firma tu carta manifiesto"
7. Iframe loads → tenant signs with their FIEL → Facturapi sends `manifest.signed` webhook
8. (If webhook reaches the server) page polling detects `manifest_signed_at` set → shows "Listo para facturar"
9. Tenant emits a CFDI from `/invoicing/new` → existing flow uses `facturapi_org_id` → CFDI emitted under the tenant's RFC

## Next phase

Review + QA. Both phases require the user to:
- Decide whether to commit Phases A+B together or split
- Actually run the flow with a real tenant
- Confirm the iframe URL works (if not, adjust `MANIFEST_IFRAME_BASE`)
- Confirm the webhook signature header name is `Facturapi-Signature` (if not, adjust `SIGNATURE_HEADER` in `services/facturapi/webhooks.py`)
