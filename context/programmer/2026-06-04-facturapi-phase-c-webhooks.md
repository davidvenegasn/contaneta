# Programmer — Phase C (Facturapi webhooks)

**Date**: 2026-06-04
**Plan**: `context/plan/2026-06-01-facturapi-multi-tenant-integration.md`
**Status**: ✅ Complete

## What changed

### New files
- `services/facturapi/__init__.py` — package marker
- `services/facturapi/webhooks.py` — `verify_signature`, `is_duplicate`, `record_received`, `mark_processed`, `dispatch`, 4 event handlers
- `routers/api/webhooks/__init__.py` — sub-router with prefix `/api/webhooks`
- `routers/api/webhooks/facturapi.py` — `POST /api/webhooks/facturapi` handler
- `migrations/058_facturapi_webhook_events.sql` — idempotency table
- `migrations/059_issuers_manifest_signed.sql` — adds `facturapi_provisioned_at` and `manifest_signed_at` columns to `issuers`
- `tests/test_facturapi_webhooks.py` — 10 tests

### Modified files
- `config.py` — added `FACTURAPI_WEBHOOK_SECRET`
- `app.py` — imported and registered `webhooks_router`
- `migrations_runner.py` — added handler for migration `059` to use `_safe_add_column` (idempotent ALTER TABLE)

## Behavior

| Scenario | Response |
|---|---|
| `FACTURAPI_WEBHOOK_SECRET` empty | 503 |
| Signature header missing/empty | 400 |
| Signature mismatch (constant-time compare) | 400 |
| Body not valid JSON | 400 |
| Event missing `id` or `type` | 400 |
| Event with valid signature, first receipt | 200 `{ok: true}` + DB row inserted + dispatch runs |
| Same event_id replayed | 200 `{ok: true, duplicate: true}` (no re-dispatch) |
| Handler raises | 500 + `process_error` persisted (Facturapi retries) |

## Dispatch table (event type → side effect)

| Event type | Effect on local DB |
|---|---|
| `invoice.cancellation_accepted` | `invoices`: `status = 'canceled'`, `cancelled = 1` |
| `invoice.cancellation_rejected` | logged only; reason kept in `payload_json` of `facturapi_webhook_events` (no schema change yet to surface it in `invoices`) |
| `invoice.status_updated` | `invoices.status = data.status` |
| `manifest.signed` | `issuers.manifest_signed_at = now()` matched by `facturapi_org_id = data.organization_id` |
| anything else | persisted in `facturapi_webhook_events`, dispatcher logs and skips |

## Open items (deliberate, not bugs)

1. **Signature header name**: hardcoded as `Facturapi-Signature` per `services/facturapi/webhooks.py:18`. If Facturapi's actual webhook uses a different header name, change `SIGNATURE_HEADER` — a real event from the dashboard will confirm.
2. **Cancellation rejection reason**: not surfaced in `invoices` because the schema has no column for it. Trace lives in `facturapi_webhook_events.payload_json`. Surface when product needs to show it (avoid scope creep now).
3. **HMAC scheme assumption**: simple HMAC-SHA256 over raw body, no timestamp prefix. If Facturapi uses a Stripe-style `t=<unix>,v1=<hmac>` scheme, `verify_signature` needs to parse the header. Confirm with a real test event.
4. **Dispatch does not call back to Facturapi**: handlers only update local state. Anything that needs an API roundtrip (e.g. fetch full invoice on `status_updated`) will be added when the product needs it.

## How to test live (USER actions)

1. Generate webhook endpoint in Facturapi dashboard:
   - Test mode → Configuración → Webhooks → Crear endpoint
   - URL: `https://<your-public-url>/api/webhooks/facturapi`
   - Suscribir eventos: `invoice.cancellation_accepted`, `invoice.cancellation_rejected`, `invoice.status_updated`, `manifest.signed` (or whatever's available — unknown types are still persisted)
   - Copy the signing secret
2. Paste into `.env` as `FACTURAPI_WEBHOOK_SECRET=...`
3. Restart server
4. In Facturapi dashboard, click "Send test event" → check `facturapi_webhook_events` table for the row + `processed_at` populated

## Tests

```
.venv/bin/pytest tests/test_facturapi_webhooks.py -v
# 10 passed

.venv/bin/pytest -q
# 835 passed, 4 skipped — no regressions (was 825 before)
```

## Next phase

Phase A: auto-provisión of Facturapi organization. Requires `FACTURAPI_SECRET_KEY` in `.env` (already confirmed by user as `sk_test_...`).
Stop here. Awaiting "implementa fase A" or similar to continue.
