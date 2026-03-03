# Launch Audit — ContaNeta

> Generated 2026-03-03. Read-only diagnostic — no code changes.

---

## 1. Architecture Overview

### Request Flow

```
Client -> Caddy/Nginx (TLS) -> Gunicorn -> FastAPI (app.py)
  -> Middleware stack (request_id -> security_headers -> redirect_token)
    -> Router (auth / portal / api / invoicing / billing / admin)
      -> Service (stateless functions)
        -> database.py -> SQLite (WAL mode)
        -> facturapi_client.py -> Facturapi API
        -> subprocess -> PHP (sat_sync/)
        -> stripe SDK -> Stripe API
        -> SMTP -> Email
```

### Module Map

| Module | Files | Purpose |
|--------|-------|---------|
| **Auth** | `routers/auth.py`, `services/session.py`, `services/csrf.py`, `services/rate_limit.py`, `routers/deps.py` | Cookie-based sessions (HMAC-SHA256), CSRF tokens, IP rate limiting |
| **Portal** | `routers/portal.py` (~2700 lines) | Server-rendered HTML pages: home, issued/received invoices, bank, settings |
| **API** | `routers/api.py` (~1700 lines) | JSON endpoints: customers, products, quotations, providers, quick-invoice, bank |
| **Invoicing** | `routers/invoicing.py`, `facturapi_client.py`, `cfdi_pdf.py` | Submit invoice -> Facturapi -> download XML/PDF |
| **SAT Sync** | `sat_sync/*.php`, `services/sat_sync.py`, `services/sat_credentials_secure.py` | FIEL validation, CFDI download from SAT via PHP subprocess |
| **Bank** | `services/bank_*.py` (20+ files) | PDF statement parsing, movement dedup, CFDI matching |
| **Jobs** | `services/jobs.py`, `worker.py` | SQLite-based queue: dedup (SHA-256), lease locking, retries |
| **Billing** | `routers/billing.py` | Stripe checkout + webhook handler |
| **Admin** | `routers/admin.py` | Issuer management, impersonation |
| **DB** | `database.py`, `migrations_runner.py`, 32 migration files | SQLite WAL, 33 tables, idempotent migrations |

### Database

- **Main:** `invoicing.db` (SQLite, WAL mode, ~7 MB)
- **Catalogs:** `catalogs/catalogs.db` (read-only SAT product/unit codes)
- **Tables:** 33 (see migration files 001–032)
- **Connection:** per-request `sqlite3.connect()`, no pooling

### Multi-Tenancy

- Tenant = Issuer (RFC/company). Every query filters by `issuer_id`.
- Session cookie: `user_id|issuer_id|expiry` (HMAC-SHA256 signed).
- `get_portal_issuer()` resolves identity and sets `request.state.{issuer_id, user_id, membership_role}`.

---

## 2. Must-Have for Launch (max 25)

### Critical (blocks launch)

| # | Item | Status | Files |
|---|------|--------|-------|
| 1 | `SESSION_SECRET` validated in prod | DONE | `config.py` |
| 2 | Cookies: `Secure`, `HttpOnly`, `SameSite=Lax` | DONE | `services/session.py` |
| 3 | CSRF on all POST endpoints | DONE | `services/csrf.py`, all routers |
| 4 | Parameterized SQL everywhere (no f-string injection) | DONE | all services |
| 5 | Tenant isolation: every query filters `issuer_id` | DONE (needs audit) | `routers/api.py`, `routers/portal.py` |
| 6 | FIEL credentials encrypted at rest | DONE | `services/crypto_at_rest.py` |
| 7 | Rate limiting on login/register | DONE (in-memory) | `services/rate_limit.py` |
| 8 | Password reset with expiration + single-use | DONE | `services/verification.py` |
| 9 | Error messages don't leak email existence | DONE | `routers/auth.py` |
| 10 | `/debug-oauth` gated behind DEV_MODE | DONE | `routers/auth.py` |
| 11 | `DEV_MODE=0` and `ALLOW_DEMO_PORTAL=0` enforced in prod | Manual check | `.env` |
| 12 | SSL/TLS termination (Caddy auto-HTTPS or cert) | Deploy step | `deploy/Caddyfile.example` |
| 13 | Database backup strategy automated | Script exists, needs cron | `scripts/backup_db.sh` |
| 14 | `SITE_URL` set (Stripe redirects, email links) | Manual check | `.env` |
| 15 | SMTP configured (or dev fallback logging) | Manual check | `services/email_sender.py` |

### Important (should fix before public)

| # | Item | Status | Files |
|---|------|--------|-------|
| 16 | Wire job handlers in worker.py `_load_handlers()` | TODO | `worker.py` |
| 17 | SAT sync triggered via job queue (not inline) | Partial | `routers/portal.py`, `worker.py` |
| 18 | Stripe webhook signature verification | DONE | `routers/billing.py` |
| 19 | Health check includes job queue stats | TODO | `app.py` |
| 20 | WAL checkpoint strategy (prevent .db-wal bloat) | TODO | `database.py` or cron |
| 21 | File download path traversal blocked | DONE | `_safe_abs_path()` in portal.py, invoicing.py |
| 22 | Structured logging (JSON to stdout) | TODO | all files |
| 23 | Gunicorn worker count + timeout configured | Template exists | `deploy/conta-invoicing.service` |

### Nice-to-Have (post-launch)

| # | Item | Files |
|---|------|-------|
| 24 | Redis-backed rate limiting for multi-process | `services/rate_limit.py` |
| 25 | Prometheus metrics endpoint | `app.py` |

---

## 3. Risks

### Alta (must address before launch)

| # | Risk | Impact | Mitigation | Files |
|---|------|--------|------------|-------|
| R1 | Rate limiting is in-memory — resets on restart, doesn't share across workers | Brute-force login after restart | Acceptable for single-process Gunicorn; document limitation | `services/rate_limit.py` |
| R2 | No DB connection pooling — each request opens/closes connection | Under load: "database is locked" errors | SQLite WAL + `busy_timeout=5000` helps; monitor in prod | `database.py` |
| R3 | Worker handlers empty — async jobs silently no-op | SAT sync jobs created but never processed | Wire `_load_handlers()` before enabling async sync | `worker.py` |
| R4 | `.env` committed accidentally | Secret leak | `.env` in `.gitignore` (DONE); add pre-commit hook | `.gitignore` |

### Media

| # | Risk | Impact | Mitigation | Files |
|---|------|--------|------------|-------|
| R5 | Bank matching O(n*m) — slow for large issuers | Timeout on >1000 movements | Add LIMIT or pagination to matching | `services/bank_cfdi_matching.py` |
| R6 | PHP subprocess timeout (SAT sync) | Hung process blocks worker | `subprocess.run(timeout=120)` already set; monitor | `services/subprocess_utils.py` |
| R7 | No backup verification — scripts exist but untested | Backup corruption undetected | Add `scripts/verify_backup.sh` | `scripts/backup_db.sh` |
| R8 | Admin impersonation has no scope restrictions | Admin can act as any issuer | Log all impersonation actions (DONE via audit_log) | `routers/admin.py` |

### Baja

| # | Risk | Impact | Mitigation | Files |
|---|------|--------|------------|-------|
| R9 | No email verification enforcement | Users with invalid emails | Verification flow exists but is optional | `routers/auth.py` |
| R10 | No 2FA | Account takeover via password | Future: TOTP or email OTP | — |
| R11 | Catalog cache 300s TTL | Stale data for 5 min after catalog update | Catalogs are read-only SAT data, rarely change | `database.py` |

---

## 4. Recommended Changes (with exact files)

### Pre-Launch

| Change | Files to Touch | Effort |
|--------|---------------|--------|
| Wire SAT sync handler in worker | `worker.py` | 1h |
| Add WAL checkpoint to cron (or app startup) | `database.py` or `scripts/wal_checkpoint.sh` | 30m |
| Create cron documentation | `docs/CRON_SETUP.md` | 30m |
| Verify tenant isolation in all 40+ API endpoints | `routers/api.py`, `routers/portal.py` | 2h |
| Add auth flow smoke tests | `scripts/smoke_release.sh` | 1h |
| Document SAT credentials flow | `docs/SAT_CREDENTIALS.md` | 30m |

### Post-Launch

| Change | Files to Touch | Effort |
|--------|---------------|--------|
| Add Prometheus metrics | `app.py`, new `services/metrics.py` | 3h |
| Structured JSON logging | `app.py`, `config.py` | 2h |
| Redis rate limiting adapter | `services/rate_limit.py` | 2h |
| Load testing with k6/locust | new `tests/load/` | 4h |
| Integration tests (full auth -> invoice flow) | `tests/test_integration.py` | 4h |
| 2FA (TOTP) | `services/totp.py`, `routers/auth.py`, templates | 8h |

---

## 5. Test Coverage Summary

| Area | Tests | Status |
|------|-------|--------|
| Health/Ready endpoints | `test_health.py` | 4 tests |
| Migration idempotence | `test_migrations.py` | 2 tests |
| Import sanity | `test_import.py` | 1 test |
| API contract shape | `test_api_contract.py` | 2 tests |
| Tenant isolation | `test_tenant_isolation.py` | 4 tests |
| Tenant download isolation | `test_tenant_isolation_downloads.py` | 4 tests |
| **Total** | | **17 tests, all pass** |

**Not tested:** Auth flows, CSRF, Stripe webhooks, SAT PHP, bank parsing edge cases, job queue, admin impersonation.

---

## 6. Environment Variables Reference

### Required in Production

```bash
ENV=prod
SESSION_SECRET=<64-char hex>          # python3 -c "import secrets; print(secrets.token_hex(32))"
APP_DB_PATH=/path/to/invoicing.db
SITE_URL=https://yourdomain.com
DEV_MODE=0
ALLOW_DEMO_PORTAL=0
COOKIE_SECURE=1
```

### Recommended

```bash
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USER=user
SMTP_PASSWORD=password
SMTP_FROM=noreply@yourdomain.com
FACTURAPI_SECRET_KEY=sk_live_...
STRIPE_SECRET_KEY=sk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...
STRIPE_PRICE_ID=price_...
```

### Optional

```bash
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
FACEBOOK_APP_ID=...
FACEBOOK_APP_SECRET=...
SESSION_TTL_DAYS=7
PORTAL_SHELL_V2=1
```
