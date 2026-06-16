# Implementation Log: Email System Scaffolding

**Date:** 2026-06-16
**Plan:** context/plan/2026-06-15-email-system-scaffolding.md

---

## Changes by File

### New files
| File | Lines | Description |
|------|-------|-------------|
| `migrations/066_email_system.sql` | 44 | CREATE TABLE email_log + ALTER TABLE issuers/customer_profiles for toggles |
| `services/email/__init__.py` | 6 | Public API exports: send_email, Attachment, EmailType, EmailStatus |
| `services/email/types.py` | 56 | EmailType enum, EmailStatus enum, Attachment, EmailMessage, SendResult dataclasses |
| `services/email/config.py` | 36 | Env var config: provider selection, from address, Resend keys |
| `services/email/sender.py` | 115 | Main send_email() entry point with template rendering + logging |
| `services/email/log.py` | 106 | CRUD helpers for email_log table (insert, mark_sent, mark_failed, webhook update) |
| `services/email/templates.py` | 35 | Jinja2 renderer for templates/emails/ |
| `services/email/queue.py` | 55 | enqueue_send_email() helper using services/jobs.enqueue_job() |
| `services/email/expiry_checker.py` | 12 | Stub for CSD/FIEL/trial expiry notification cron |
| `services/email/providers/__init__.py` | 2 | Package init |
| `services/email/providers/base.py` | 12 | EmailProvider ABC |
| `services/email/providers/noop.py` | 20 | NoopProvider (logs, doesn't send) |
| `services/email/providers/resend.py` | 72 | ResendProvider (HTTP API via httpx, no SDK) |
| `routers/api/webhooks/resend.py` | 65 | Webhook endpoint /api/webhooks/resend for Resend events |
| `templates/emails/base.html` | 37 | Base email layout with brand, content block, footer |
| `templates/emails/invoice_sent.html` | 17 | Invoice sent notification |
| `templates/emails/declaration_summary.html` | 27 | Declaration summary notification |
| `templates/emails/welcome.html` | 10 | Welcome after registration |
| `templates/emails/email_verification.html` | 8 | Email verification link |
| `templates/emails/password_reset.html` | 8 | Password reset link |
| `templates/emails/csd_expiring.html` | 14 | CSD expiring alert |
| `templates/emails/fiel_expiring.html` | 14 | FIEL expiring alert |
| `templates/emails/trial_expiring.html` | 8 | Trial expiring notification |
| `templates/emails/subscription_renewed.html` | 11 | Subscription renewed confirmation |
| `templates/emails/payment_failed.html` | 14 | Payment failed alert |
| `tests/test_email_system.py` | 138 | 15 tests for config, providers, templates, sender, log |
| `tests/test_email_webhook.py` | 71 | 4 tests for webhook endpoint |
| `docs/email_setup.md` | 33 | Production email setup guide |

### Modified files
| File | Changes |
|------|---------|
| `worker.py` | Added `handle_send_email` handler + registered as `"send_email"` in `_load_handlers()` |
| `routers/api/webhooks/__init__.py` | Added import of `resend` module to register webhook route |
| `.env.example` | Added EMAIL_PROVIDER, EMAIL_FROM_NAME, EMAIL_FROM_ADDRESS, RESEND_API_KEY, RESEND_WEBHOOK_SECRET, EMAIL_SUPPORT_ADDRESS |
| `routers/invoicing.py` | Added TODO comment for invoice_sent email trigger |
| `routers/auth/register.py` | Added 2 TODO comments for welcome + email_verification triggers |
| `routers/auth/password.py` | Added TODO comment for password_reset confirmation trigger |

---

## Decision on existing email modules

**`services/email_sender.py`** (SMTP-based) and **`services/email_templates.py`** (Jinja2 render helpers) were **NOT touched**, per plan constraint. The new `services/email/` subsystem is built side-by-side. When the new system is fully connected (follow-up job), the old SMTP modules can be deprecated.

---

## Adaptation to real `services/jobs.enqueue_job()` signature

The plan's `enqueue_send_email` assumed a generic `enqueue(job_type, payload)` API. The real signature is:

```python
enqueue_job(name: str, issuer_id: int, payload: dict | None, *, run_after, max_attempts, priority)
```

Key difference: `issuer_id` is required as `int`. For system-level emails (welcome, password reset) without a specific issuer, `queue.py` passes `issuer_id or 0`.

---

## Webhook URL deviation

The plan specified `/webhooks/resend`. The actual codebase already has a webhooks infrastructure at `routers/api/webhooks/` with prefix `/api/webhooks`. For consistency, the Resend webhook was mounted at **`/api/webhooks/resend`** instead.

---

## Test Results

```
19 new tests: ALL PASSED
Full suite: 914 passed, 12 failed (pre-existing), 4 skipped, 9 deselected
Baseline:   895 passed, 12 failed (pre-existing), 4 skipped, 9 deselected
Delta: +19 passed, 0 new failures
```

`python -c "import app"` → OK

---

## Trigger Points TODO (5 locations)

1. **`routers/invoicing.py:579`** — after timbrado success, before template response
   ```python
   # TODO: enqueue_send_email for invoice_sent if customer.email and customer.auto_send_invoices and issuer.email_notifications_enabled
   ```

2. **`routers/auth/register.py:188`** — signup path, after audit.log
   ```python
   # TODO: enqueue_send_email for welcome template after registration
   ```

3. **`routers/auth/register.py:264`** — register path, after audit.log
   ```python
   # TODO: enqueue_send_email for email_verification template
   ```

4. **`routers/auth/password.py:86`** — after password update
   ```python
   # TODO: enqueue_send_email for password_reset confirmation
   ```

5. **`services/email/expiry_checker.py`** — stub module
   ```python
   # TODO: cron job that iterates issuers and enqueues csd_expiring / fiel_expiring / trial_expiring emails
   ```

---

## First real send example (once domain + RESEND_API_KEY configured)

```python
from services.email.sender import send_email

# Synchronous send (for time-critical flows like password reset)
log_id = send_email(
    to_email="cliente@empresa.com",
    template="welcome",
    context={"user_name": "María", "brand_name": "ContaNeta"},
    email_type="welcome",
    user_id=42,
    issuer_id=7,
)

# Async send via job queue (for non-critical flows like invoices)
from services.email.queue import enqueue_send_email
job_id = enqueue_send_email(
    to_email="receptor@empresa.com",
    template="invoice_sent",
    context={
        "from_name": "ACME SA de CV",
        "total": 15000.0,
        "currency": "MXN",
        "serie": "A",
        "folio": "456",
        "fecha_emision": "2026-06-16",
        "uuid": "abc-123-def-456",
    },
    issuer_id=7,
    email_type="invoice_sent",
    related_object_type="invoice",
    related_object_id=123,
)
# Then: python worker.py --once  (will pick up and send)
```

---

## Acceptance Criteria Status

- [x] Migración 066 aplicada, idempotente
- [x] Tabla `email_log` existe con todas las columnas listadas
- [x] Columnas `email_notifications_enabled` (issuers) y `auto_send_invoices` (customer_profiles) existen
- [x] `services/email/` con todos los módulos descritos
- [x] Provider `noop` funciona y es el default sin RESEND_API_KEY
- [x] Provider `resend` existe con HTTP client a Resend API (sin SDK)
- [x] `templates/emails/` con todas las plantillas listadas (base + 10 templates)
- [x] Handler `send_email` registrado en `worker.py`
- [x] Helper `enqueue_send_email` funciona y usa la firma correcta de `services/jobs.enqueue_job`
- [x] Webhook endpoint `/api/webhooks/resend` montado en app
- [x] Variables nuevas en `.env.example`
- [x] 5 TODO markers añadidos en los trigger points
- [x] `tests/test_email_system.py` y `tests/test_email_webhook.py` pasan (19/19)
- [x] `.venv/bin/pytest -q` no introduce nuevas fallas (baseline = 12 → 12)
- [x] `.venv/bin/python -c "import app"` sigue limpio
- [x] `docs/email_setup.md` describe el procedimiento de swap

---

## Deviations from Plan

1. **Webhook URL**: `/api/webhooks/resend` instead of `/webhooks/resend` — existing webhook infrastructure lives at `routers/api/webhooks/` with that prefix.
2. **Expiry checker location**: Created at `services/email/expiry_checker.py` instead of `services/notifications/expiry_checker.py` — `services/notifications.py` exists as a file (in-app notification service), so creating a `services/notifications/` directory would conflict.
3. **`render_subject` via Jinja2 block**: Used the simpler `SUBJECTS_BY_TEMPLATE` dict approach as the plan recommended when the block-based approach is fragile.
4. **`datetime.utcnow()` → `datetime.now(timezone.utc)`**: Fixed deprecation warnings in `log.py` for Python 3.12+ compatibility.
