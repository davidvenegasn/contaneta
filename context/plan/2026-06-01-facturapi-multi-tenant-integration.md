# Plan — Facturapi multi-tenant integration

**Date**: 2026-06-01
**Research doc**: `context/research/2026-06-01-facturapi-multi-tenant-integration.md`
**Scope**: implement the 3 blockers identified in Research (webhooks, auto-provisión, manifesto embebido) in that order.
**Target environment**: TEST first, single env-var flip to LIVE when validated.

---

## Pre-flight checklist (USER must complete)

| # | Action | Done? |
|---|---|---|
| 1 | `.env` has line `FACTURAPI_SECRET_KEY=sk_live_...` (master User Key) | TBC |
| 2 | `.env` has line `FACTURAPI_TEST_KEY=sk_test_...` (TEST master User Key) for sandbox validation | TBC |
| 3 | In Facturapi dashboard → Configuración → Webhooks → create endpoint placeholder for `https://<your-domain>/api/webhooks/facturapi`, copy signing secret → paste in `.env` as `FACTURAPI_WEBHOOK_SECRET=...` | TBC |
| 4 | Rotated the Live Secret Key that was leaked in chat (recommended, not gating) | TBC |

The implementation will run regardless of #3 being filled (the webhook code reads the env at request time and 503s gracefully if not set). #1 is required for the existing emission to keep working; nothing new needs from the user before the code lands.

---

## Phase C — Webhook handler (FIRST, lowest blast radius)

### Goal
Receive `POST /api/webhooks/facturapi`, verify HMAC signature, persist with idempotency, dispatch to handlers. Stub event handlers — they will update local state but not break if the event payload shape is unexpected.

### Files

#### NEW `services/facturapi/__init__.py` (empty package marker, ≤5 lines)

#### NEW `services/facturapi/webhooks.py` (~150 lines)
Public API:
```python
def verify_signature(body: bytes, header_value: str, secret: str) -> bool
def is_duplicate(event_id: str) -> bool
def record_received(event_id: str, event_type: str, payload: dict) -> None
def dispatch(event: dict) -> None
```
- `verify_signature` uses `hmac.compare_digest` with SHA-256 over raw body. Header name TBD during implementation (likely `Facturapi-Signature`; will inspect a real test webhook from dashboard).
- `is_duplicate` and `record_received` use the new `facturapi_webhook_events` table.
- `dispatch` routes by `event.type`:
  - `invoice.cancellation_accepted` → updates `invoices` and `sat_cfdi` (set canceled_at)
  - `invoice.cancellation_rejected` → logs + sets `cancel_status`
  - `invoice.status_updated` → upserts `sat_status` field
  - `manifest.signed` → sets `issuers.manifest_signed_at` (new column, see Migration)
  - default: log + persist for inspection

#### NEW `migrations/058_facturapi_webhook_events.sql`
```sql
CREATE TABLE IF NOT EXISTS facturapi_webhook_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id TEXT NOT NULL UNIQUE,
  event_type TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  received_at DATETIME NOT NULL DEFAULT (datetime('now')),
  processed_at DATETIME,
  process_error TEXT
);
CREATE INDEX IF NOT EXISTS idx_fpi_webhook_type ON facturapi_webhook_events(event_type);
```

#### NEW `migrations/059_issuers_manifest_signed.sql`
```sql
ALTER TABLE issuers ADD COLUMN manifest_signed_at DATETIME;
ALTER TABLE issuers ADD COLUMN facturapi_provisioned_at DATETIME;
```

#### NEW `routers/api/webhooks/__init__.py` + `routers/api/webhooks/facturapi.py` (~80 lines)
Mirrors `routers/billing.py:79-130` (Stripe pattern):
- `@router.post("/api/webhooks/facturapi")`
- Read raw body, read `X-Facturapi-Signature` header
- 503 if `FACTURAPI_WEBHOOK_SECRET` not configured
- 400 if signature invalid
- 200 if duplicate (idempotent ack)
- Try `dispatch(event)`; on exception, persist `process_error` and 500 so Facturapi retries
- Always log to `services.action_log.log_action`

#### MODIFIED `config.py`
Add: `FACTURAPI_WEBHOOK_SECRET = os.getenv("FACTURAPI_WEBHOOK_SECRET", "")`.

#### MODIFIED `app.py`
Register the new router: `app.include_router(facturapi_webhooks_router)`.

#### MODIFIED `.env.example`
Add `FACTURAPI_WEBHOOK_SECRET=` with comment.

### Tests
- `tests/test_facturapi_webhooks.py`:
  - `test_should_503_when_secret_not_configured`
  - `test_should_400_when_signature_invalid`
  - `test_should_200_when_duplicate_event`
  - `test_should_persist_event_on_first_receipt`
  - `test_should_dispatch_invoice_cancellation_accepted` (using a frozen sample payload)

### Acceptance criteria for Phase C
- Migrations apply cleanly on dev DB.
- `pytest tests/test_facturapi_webhooks.py -v` green.
- No regression: `pytest -q` green.
- Endpoint responds to a sample POST with valid signature → 200, duplicate POST → 200, bad signature → 400.

---

## Phase A — Auto-provisión of Facturapi organization

### Goal
When a new issuer is created in ContaNeta, a corresponding Facturapi organization is created and its `id` is stored in `issuers.facturapi_org_id`. **Must NOT block signup if Facturapi is unreachable** — provision asynchronously via the job queue.

### Files

#### NEW `services/facturapi/orgs.py` (~120 lines)
Public API:
```python
def create_organization(issuer_id: int) -> str
def upload_csd(org_id: str, cer_bytes: bytes, key_bytes: bytes, password: str) -> dict
def update_legal_info(org_id: str, *, legal_name: str, tax_id: str, tax_system: str, address: dict) -> dict
def get_test_api_key(org_id: str) -> str  # optional, for later
```
- `create_organization` reads RFC, razón social, régimen, CP from `issuers` row → `POST /v2/organizations` with Bearer `FACTURAPI_SECRET_KEY` → returns `org_id`.
- `upload_csd` → `PUT /v2/organizations/{id}/certificate` (exact endpoint path verified during impl by hitting the API once).
- All functions raise `FacturapiError` from `facturapi_client` on non-2xx.

#### NEW `services/jobs/handlers/facturapi_provision.py` (~60 lines)
Job handler `facturapi_provision_org`:
- Read issuer row.
- Skip if `facturapi_org_id` already populated.
- Call `services.facturapi.orgs.create_organization(issuer_id)`.
- On success, `UPDATE issuers SET facturapi_org_id = ?, facturapi_provisioned_at = datetime('now')`.
- On failure: re-raise to let the job runner retry per `max_attempts`.

#### MODIFIED `worker.py:_load_handlers()`
Register `"facturapi_provision_org": handle_facturapi_provision_org`.

#### MODIFIED `services/issuers.py:create_issuer_with_token`
After existing INSERT block (lines 188-205), enqueue the job:
```python
from services import jobs as jobs_service
jobs_service.enqueue_job(
    name="facturapi_provision_org",
    issuer_id=issuer_id,
    payload={"reason": "signup"},
    max_attempts=5,
)
```
This is the ONLY change to the hot path: an INSERT into `jobs`. No external HTTP call inline.

#### NEW `routers/portal/facturapi_status.py` (~80 lines)
- `GET /portal/api/facturapi/status` → returns `{ provisioned: bool, org_id: str|null, manifest_signed: bool, csd_uploaded: bool }` for the current issuer. Used by the manifesto page to poll.

#### NEW endpoint `POST /portal/api/facturapi/upload-csd`
- Accepts `.cer`, `.key`, password via multipart.
- Validates with existing FIEL/CSD parser (`services/sat/sat_credentials_secure.py:extract_fiel_subject` analog).
- Calls `services.facturapi.orgs.upload_csd(org_id, ...)`.
- Persists locally too (existing flow) so the PHP SAT sync still works.

### Tests
- `tests/test_facturapi_orgs.py`:
  - `test_should_enqueue_provision_job_on_create_issuer`
  - `test_should_skip_provision_when_org_id_already_set`
  - `test_handler_persists_org_id_on_success` (mocked HTTP)
  - `test_handler_retries_on_5xx` (mocked HTTP)

### Acceptance criteria for Phase A
- New signup creates a `jobs` row of name `facturapi_provision_org`.
- Worker processes it → `issuers.facturapi_org_id` populated within seconds.
- Signup endpoint latency unchanged (no synchronous Facturapi call in hot path).
- CSD upload from portal → Facturapi org has the cert.

---

## Phase B — Embedded manifesto page

### Goal
A portal page where the tenant signs their carta manifesto using Facturapi's iframe, without leaving ContaNeta.

### Open questions (resolve during impl)
- Iframe URL params: `?organization_id=<facturapi_org_id>` likely, plus possibly a signed JWT minted via Facturapi's `/v2/organizations/{id}/manifest-link` endpoint or similar.
- Auth: cookie inside iframe vs PostMessage handshake.
- Completion signal: `manifest.signed` webhook (already handled by Phase C dispatcher).

I will resolve these by inspecting Facturapi's dashboard webhook test feature + their published embedded UI docs once we get there.

### Files

#### NEW `routers/portal/onboarding_manifesto.py` (~70 lines)
- `GET /portal/setup/manifiesto` — renders `portal_manifesto.html`.
  - Reads current issuer via `Depends(get_portal_issuer)`.
  - If `facturapi_org_id` is NULL → render "preparando tu cuenta, vuelve en unos segundos" with auto-refresh.
  - If org_id exists → render iframe with the right URL.
  - If `manifest_signed_at` already set → render "ya está firmada ✓" + CTA to next step.

#### NEW `templates/portal_manifesto.html` (~80 lines)
Extends `base_portal_v2.html`. Three states:
1. Pending (provisioning) — spinner + JS polling `/portal/api/facturapi/status` every 3s.
2. Ready to sign — iframe loaded with `data-iframe-url` attribute.
3. Signed — success state + link to "subir CSD" or "emitir primera factura".

#### MODIFIED `templates/components/portal_sidebar_unified.html`
Add a setup item in the nav for "Configurar facturación" that links to `/portal/setup/manifiesto` UNTIL `manifest_signed_at` is set. Conditional render based on a context flag passed from base.

#### MODIFIED `routers/portal/_helpers.py` (or wherever base portal context is built)
Pass `manifest_signed: bool` into all portal templates so the sidebar can conditionally show the setup link.

### Tests
- `tests/test_portal_manifesto.py`:
  - `test_should_show_pending_when_org_not_provisioned`
  - `test_should_show_iframe_when_org_ready_and_not_signed`
  - `test_should_show_success_when_manifest_signed`
  - `test_status_endpoint_returns_correct_state`

### Acceptance criteria for Phase B
- `/portal/setup/manifiesto` renders without errors for any portal user.
- Iframe is sandboxed correctly (`sandbox="allow-scripts allow-same-origin allow-forms"` minimum).
- When `manifest.signed` webhook arrives, the page (if open) auto-detects via polling and switches to success state.

---

## Cross-cutting decisions

- **Auth strategy for Facturapi calls**: keep using Bearer master User Key + `Facturapi-Organization` header (current `facturapi_client.py` pattern). Do NOT switch to per-org keys in this iteration — would touch the emission path and breaks rule "behavior must not change in refactors". Per-org keys can be a future optimization.
- **TEST vs LIVE**: env var `FACTURAPI_SECRET_KEY` decides. To validate, temporarily set it to `FACTURAPI_TEST_KEY` value. No code branch needed.
- **Idempotency**: every external Facturapi call must be safe to retry. Job queue handles this for provisioning. Webhook table handles it for events.

---

## Order of execution + estimated effort

| Phase | Effort (focused work) | Risk |
|---|---|---|
| C — webhooks | ~3-4h | Low |
| A — auto-provisión + CSD upload | ~4-5h | Med (touches signup) |
| B — manifesto iframe | ~3-4h | Med (Facturapi iframe params unknown) |
| Review + QA | ~2h | — |
| **Total** | **~12-15h** | — |

Each phase commits independently. Each phase has its own test file. Run `.venv/bin/pytest -q` at start and after each phase.

---

## Out of scope (do NOT implement here)

- Factura Global, Exportación, Comercio Exterior
- Switch from header-based auth to per-org API keys
- Webhook event types beyond the 4 listed
- White-label PDF customization (handled later via Facturapi dashboard)
- Email-from-tenant branding (handled later)

---

## Stop here

Awaiting "implementa" or "pasa al programmer" to start Phase C. The user must also:
1. Confirm `FACTURAPI_SECRET_KEY` is in `.env` (block A's job will fail otherwise — fail-soft, but won't provision).
2. Generate webhook signing secret in Facturapi dashboard and put in `.env` as `FACTURAPI_WEBHOOK_SECRET` (block C's endpoint will 503 otherwise — graceful).
