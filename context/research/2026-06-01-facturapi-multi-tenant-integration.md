# Research — Facturapi multi-tenant integration (3 blockers)

**Date**: 2026-06-01
**Scope**: Close the gaps required for ContaNeta tenants to self-onboard with Facturapi (org auto-provisioning, embedded manifesto, webhook handler).
**Out of scope**: rewriting existing emission flow, factura global, exportación, comercio exterior.

---

## 1. Context — what already works

ContaNeta is already emitting real CFDIs via Facturapi for Ingreso (I), Egreso/Nota de Crédito, Pago, and cancellations across all 4 SAT motives. The emission path is solid; the gap is everything that has to happen **before** a tenant can emit and **after** an asynchronous event occurs at the SAT.

Confirmed via codebase exploration and Facturapi support (chat with Fin AI):

- **Auth model**: one master User Key per ContaNeta account, all calls scoped to a tenant by passing `organization_id` (no per-org API key rotation required, though per-org keys do exist).
- **Test vs Live**: separate API keys (`sk_test_*` / `sk_live_*`); current `.env` carries `FACTURAPI_SECRET_KEY` + `FACTURAPI_TEST_KEY`.
- **Organizations**: no limit, no extra cost per org. Only billed per timbre emitted in Live. Cancellations are free.
- **Embedded manifesto iframe**: exists at `https://www.facturapi.io/embedded/manifiesto` — tenants can sign their own carta manifiesto without leaving ContaNeta.

---

## 2. Current state — where the gaps are

### 2.1 Issuer creation does NOT auto-provision a Facturapi organization

`services/issuers.py:174` `create_issuer_with_token()` is the single insertion point for new tenants. It writes to `issuers` and `issuer_tokens`, then returns `(issuer_id, token)`. It is called from:

- `routers/auth/register.py:162` — `/signup` flow
- `routers/auth/register.py:238` — `/auth/register` flow

`facturapi_org_id` is added to the schema (`migrations/002_add_facturapi_org_id.sql`) and read everywhere it matters, but **no code path writes to it**. Grep for `facturapi_org_id =` in non-test code: zero hits. Tenants today get the column populated manually via admin tools or seed scripts (`scripts/seed_dev.py`).

→ **Gap A**: auto-provision a Facturapi organization at issuer creation time and persist its `id` to `issuers.facturapi_org_id`.

### 2.2 No portal page for signing the carta manifiesto

Facturapi exposes an embedded iframe (`/embedded/manifiesto`). ContaNeta has no page that loads it. Today the tenant would have to go to Facturapi's dashboard with credentials they don't have — which breaks the white-label promise.

→ **Gap B**: portal page `/portal/setup/manifiesto` (or similar) that loads the iframe scoped to the current tenant's org.

### 2.3 No webhook handler for Facturapi events

`docs/guides/facturapi_integration_guide.md:51-54` flags `POST /api/webhooks/facturapi` as planned but not implemented. Without it, the only mechanism to learn about async state changes (e.g. SAT cancellation accepted/rejected, complemento de pago events, manifesto signed) is the existing PHP-based SAT sync (eventual consistency, hours of delay).

The Stripe webhook in `routers/billing.py:79-100` is the template to follow:
- raw body capture
- header-based signature verification
- explicit event-type dispatch
- idempotency by event ID

→ **Gap C**: add `POST /api/webhooks/facturapi` with HMAC verification, idempotency, and dispatch table for: `manifest.signed`, `invoice.cancellation_accepted`, `invoice.cancellation_rejected`, `invoice.status_updated`.

---

## 3. What the Facturapi API surface looks like (confirmed + assumed)

### 3.1 Confirmed by Facturapi support

| Endpoint | Purpose |
|---|---|
| `POST /v2/organizations` | Create new tenant org. Auth: Bearer User Key. Returns org with `id`. |
| `PUT /v2/organizations/{id}` (datos fiscales) | Update legal name, regime, address. |
| `PUT /v2/organizations/{id}/certificate` | Upload `.cer` + `.key` + password (CSD). |
| `GET /v2/organizations/{id}/apikeys/test` | Retrieve sandbox key for that org. |
| `GET /v2/organizations/{id}/apikeys/live` | Retrieve live key(s). |
| `https://www.facturapi.io/embedded/manifiesto` | Iframe to sign carta manifesto. URL params TBD (see §4). |

### 3.2 Authentication strategy decision

The existing `facturapi_client.py` uses `Authorization: Bearer {FACTURAPI_SECRET_KEY}` + custom header `Facturapi-Organization: {org_id}` for routing. This works today for emission.

**Question to resolve in Plan phase**: do we keep that header pattern, or do we fetch and store per-org API keys at provisioning time and use those? The header approach is simpler. The per-org-key approach is what Facturapi's docs typically show.

Decision criteria: whichever Facturapi's current API actually supports without surprises. The current code is in production for emission, so it works today — but if per-org keys are the documented path, we should align.

### 3.3 Open questions for the iframe

- **URL params**: how does the iframe know which org to load? Likely a signed URL or a query param like `?organization_id=...&token=...`.
- **Auth**: does it require a JWT we mint server-side, or does it auth via cookie/parent-window message?
- **Callback**: how does ContaNeta know the manifesto was signed? Webhook event (`manifest.signed`)? PostMessage from iframe?

→ Will resolve by reading docs.facturapi.io interactively during Plan phase (their docs page is JS-rendered, can't be scraped via WebFetch).

### 3.4 Open questions for webhooks

- Signature header name (likely `Facturapi-Signature` or `X-Facturapi-Signature`).
- HMAC algorithm (probably SHA-256).
- Secret rotation: account-wide vs per-org.
- Event type list: full list TBD. Known: at least `invoice.created`, `invoice.cancelled`, `invoice.status_updated`.

→ Will resolve by checking the Facturapi dashboard webhook config UI (user can copy the secret + see the docs link).

---

## 4. Files that will be touched (preview only — not a plan yet)

```
NEW
├── routers/api/webhooks/facturapi.py       — POST /api/webhooks/facturapi
├── routers/portal/onboarding_manifesto.py  — GET /portal/setup/manifiesto
├── services/facturapi/orgs.py              — create_organization(), get_org_api_keys()
├── services/facturapi/webhooks.py          — verify_signature(), dispatch(event)
├── templates/portal_manifesto.html         — iframe shell + status polling
├── migrations/0NN_facturapi_webhook_events.sql — idempotency table for received events

MODIFIED
├── services/issuers.py                     — create_issuer_with_token() calls orgs.create_organization()
├── facturapi_client.py                     — possibly switch to per-org API key, or leave as-is
├── app.py                                  — register new routers
├── .env.example                            — add FACTURAPI_WEBHOOK_SECRET
```

---

## 5. Risks & sequencing

### 5.1 Order to implement (recommended)

1. **Webhooks first** (Gap C). Lower blast radius — pure receive-side, no risk of breaking emission. Stripe pattern in `routers/billing.py` is the template. Even an empty handler that just persists + ACKs is valuable.
2. **Org auto-provision** (Gap A). Touches the hot path of tenant signup. Must be idempotent + fail-soft (if Facturapi is down at signup, don't block the tenant — retry job).
3. **Embedded manifesto** (Gap B). Depends on (1) for the `manifest.signed` event and (2) for the org to exist. Last because the iframe params/auth are the biggest unknown.

### 5.2 Risks

- **Auto-provision during signup is a foreign API call in the hot path.** If Facturapi rate-limits or is slow, tenant signup degrades. Mitigation: queue the org creation as a job (`services/jobs.py` already exists) and set `facturapi_org_id = NULL` until processed. Block emission until populated.
- **Webhook idempotency**. Facturapi may retry on 5xx. Need a `webhook_events_received` table keyed on `event_id`.
- **Manifesto iframe in TEST vs LIVE**. Tenant's TEST org has a generic RFC; LIVE org has the real one. The iframe must point to the right environment. Decision: only expose the iframe for the LIVE org once the CSD upload has set the real RFC.
- **CSD upload flow not yet wired to Facturapi org**. ContaNeta currently stores FIEL/CSD locally (`services/sat/sat_credentials_secure.py`) for the PHP-based SAT sync. We need a separate upload step that sends the CSD to Facturapi via `PUT /v2/organizations/{id}/certificate`. This is implicit in Gap A but worth calling out — could be a Gap A.5.

---

## 6. What's needed from the user before Plan phase

| # | Item | Where |
|---|---|---|
| 1 | Confirm `FACTURAPI_SECRET_KEY` (User Key master, NOT an org key) is in `.env` and is a live User Key | open `.env`, look for `FACTURAPI_SECRET_KEY=` |
| 2 | Webhook signing secret (will need to generate one in dashboard) | dashboard.facturapi.io → Webhooks → generate endpoint |
| 3 | Confirm we want to ship Test mode first, then flip Live, vs Live-only | strategy call |

---

## 7. Recommendation

Proceed to Plan phase with the three-blocker scope. Order: **C → A → B**. Open questions (§3.3, §3.4) will be resolved during plan/implement by hitting the actual API + dashboard, not by speculating from outdated docs.

Stop here. Awaiting "pasa al planner" to continue.
