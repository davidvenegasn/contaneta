# Stripe Webhook Security Audit — ContaNeta

**Date:** 2026-05-12

## Implementation

**File:** `routers/billing.py` — POST `/webhooks/stripe`

## Findings

| Check | Status | Notes |
|-------|--------|-------|
| Validates signature with STRIPE_WEBHOOK_SECRET | ✅ | `stripe.Webhook.construct_event()` — returns 400 on failure |
| Idempotent (same event.id not processed twice) | ❌ | No event.id tracking. Duplicate events cause duplicate DB updates |
| Logs event.type and subscription info | ✅ | Via `log_action()` |
| No sensitive info in error responses | ✅ | Generic "Payload inválido" / "Firma inválida" |
| Requires STRIPE_WEBHOOK_SECRET configured | ✅ | Returns 503 if not set |

## Events Handled

| Event Type | Action |
|------------|--------|
| `checkout.session.completed` | Upserts subscription (plan=pro, status=active) |
| `customer.subscription.updated` | Updates status or period end |
| `customer.subscription.deleted` | Marks subscription canceled |

## Idempotency Gap

The webhook handler does not track `event.id`. If Stripe retries a webhook (e.g., due to timeout), the handler processes it again. For `checkout.session.completed`, `upsert_subscription` is already idempotent (INSERT OR UPDATE). For status changes, re-applying the same status is harmless. **Risk is LOW** — no data corruption, but `log_action` entries may duplicate.

### Recommended Fix

Add an `event_id` column to a small `stripe_events` table:
```sql
CREATE TABLE IF NOT EXISTS stripe_webhook_events (
    event_id TEXT PRIMARY KEY,
    event_type TEXT,
    processed_at TEXT DEFAULT (datetime('now'))
);
```
Check before processing: `SELECT 1 FROM stripe_webhook_events WHERE event_id = ?`. Skip if exists.

## Security Assessment

- **Signature verification**: GOOD — uses Stripe's official SDK `construct_event` with HMAC verification
- **Secret management**: GOOD — `STRIPE_WEBHOOK_SECRET` from env, not hardcoded
- **Error handling**: GOOD — no stack traces or sensitive data in 400 responses
- **Auth**: N/A — webhook endpoints use signature verification, not session auth

**Overall**: SECURE. Idempotency gap is low risk since all operations are naturally idempotent or append-only.
