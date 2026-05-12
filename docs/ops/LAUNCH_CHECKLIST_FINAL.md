# Production Launch Checklist — ContaNeta v1.0

**Last updated:** 2026-05-12
**Status:** Pre-launch

This is the consolidated, definitive checklist for production deployment. References all security audits and operational runbooks produced during the hardening sprint.

---

## 1. Security Audits (All Completed)

| Audit | Doc | Tests | Status |
|-------|-----|-------|--------|
| Tenant isolation | [tenant_isolation_audit.md](tenant_isolation_audit.md) | `test_tenant_isolation.py` (6 tests) | PASS — no cross-tenant leaks |
| SAT credentials (FIEL) | [sat_credentials_audit.md](sat_credentials_audit.md) | `test_sat_credentials_security.py` (4 tests) | PASS — AES-256-GCM |
| Stripe webhooks | [stripe_webhook_audit.md](stripe_webhook_audit.md) | `test_billing_webhook.py` (3 tests) | PASS — sig verified |
| HTTP security headers | [security_headers_audit.md](security_headers_audit.md) | `test_security_headers.py` (6 tests) | PASS — CSP, X-Frame, etc. |
| Session & cookies | [session_security_audit.md](session_security_audit.md) | `test_session_security.py` (5 tests) | PASS — HMAC-SHA256 |
| Rate limiting | [RATE_LIMITING_AUDIT.md](RATE_LIMITING_AUDIT.md) | — | PASS — login/register limited |
| LFPDPPP (privacy) | [lfpdppp_compliance_audit.md](lfpdppp_compliance_audit.md) | — | Phase 1 implemented |
| DB indexes | [DB_INDEXES_AUDIT.md](DB_INDEXES_AUDIT.md) | — | 60+ existing, 5 recommended |

### Known Accepted Risks

| Risk | Severity | Mitigation |
|------|----------|-----------|
| No session invalidation on password change | LOW-MEDIUM | 7-day TTL, HMAC integrity |
| HSTS header not set (handled by Caddy) | LOW | Caddy auto-adds HSTS |
| Stripe webhook no idempotency key | LOW | Duplicate events are safe (upsert logic) |
| FIEL upload constants undefined after portal split | HIGH | Fix before launch — restore ALLOWED_CER/KEY/MAX_FIEL_SIZE |

---

## 2. Environment Variables

### Required in Production

```bash
# Core (MANDATORY)
ENV=prod
DEV_MODE=0
SESSION_SECRET=<python3 -c "import secrets; print(secrets.token_hex(32))">
APP_DB_PATH=/opt/contaneta/data/invoicing.db
SITE_URL=https://app.contaneta.com
COOKIE_SECURE=1
ALLOW_DEMO_PORTAL=0

# Email (MANDATORY for password reset)
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USER=noreply@contaneta.com
SMTP_PASSWORD=<app-password>
SMTP_FROM=noreply@contaneta.com

# Encryption (RECOMMENDED — auto-derived from SESSION_SECRET if not set)
AT_REST_MASTER_KEY=<python3 -c "import secrets; print(secrets.token_hex(32))">
```

### Optional

```bash
# Billing
STRIPE_SECRET_KEY=sk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...
STRIPE_PRICE_ID=price_...

# OAuth
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
```

### Validate

```bash
.venv/bin/python scripts/validate_env.py
```

---

## 3. Pre-Deploy Checks

- [ ] `ENV=prod` and `DEV_MODE=0` in `.env`
- [ ] `SESSION_SECRET` is a unique random hex (≥32 bytes)
- [ ] `COOKIE_SECURE=1`
- [ ] `ALLOW_DEMO_PORTAL=0`
- [ ] `/docs`, `/redoc`, `/openapi.json` return 404 (gated behind DEV_MODE)
- [ ] SMTP configured and tested (send a test email)
- [ ] Stripe webhook endpoint configured in Stripe dashboard
- [ ] SAT FIEL upload validation constants restored (ALLOWED_CER, ALLOWED_KEY, MAX_FIEL_SIZE)
- [ ] `scripts/validate_env.py` passes all checks
- [ ] Database migrations applied (`python -c "from migrations_runner import apply_migrations; apply_migrations()"`)

---

## 4. Deploy

See [AWS_DEPLOY.md](AWS_DEPLOY.md) for full AWS guide.

```bash
# Quick deploy
git clone <repo> /opt/contaneta/app && cd /opt/contaneta/app
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env  # Edit with production values
mkdir -p /opt/contaneta/data storage keys && chmod 700 keys

# Systemd
sudo cp deploy/conta-invoicing.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now conta-invoicing

# Reverse proxy (Caddy)
sudo cp deploy/Caddyfile.example /etc/caddy/Caddyfile
# Edit domain, then: sudo systemctl reload caddy
```

---

## 5. Post-Deploy Verification

```bash
BASE=https://app.contaneta.com

# Health checks
curl -sf "$BASE/health" | jq .status        # "ok"
curl -sf "$BASE/ready" | jq .ready          # true
curl -sf "$BASE/healthz" | jq .status       # "ok" (K8s alias)

# Security checks
curl -sI "$BASE/health" | grep -i "x-content-type-options"  # nosniff
curl -sI "$BASE/health" | grep -i "x-frame-options"         # DENY
curl -sf "$BASE/docs" -o /dev/null -w '%{http_code}'         # 404 (not 200)

# Auth enforcement
curl -sf "$BASE/api/customers" -o /dev/null -w '%{http_code}'  # 401

# Full smoke suite
.venv/bin/pytest tests/test_smoke_routes.py -v
```

---

## 6. Background Services

### Worker

```bash
sudo cp deploy/contaneta-worker.service /etc/systemd/system/  # if available
# Or via cron:
* * * * * cd /opt/contaneta/app && .venv/bin/python worker.py --once >> /var/log/contaneta/worker.log 2>&1
```

### SAT Sync

```bash
0 */6 * * * cd /opt/contaneta/app && bash sat_sync/cron_sat_sync.sh >> /var/log/contaneta/sat-sync.log 2>&1
```

### WAL Checkpoint

```bash
0 */4 * * * sqlite3 /opt/contaneta/data/invoicing.db 'PRAGMA wal_checkpoint(TRUNCATE);' >> /var/log/contaneta/wal.log 2>&1
```

---

## 7. Backups

See [backup_production.md](backup_production.md) for full runbook.

- [ ] `scripts/backup_to_s3.sh` configured (renamed from `.example`)
- [ ] S3 bucket created with versioning enabled
- [ ] Systemd timer installed: `deploy/backup.timer` + `deploy/backup.service`
- [ ] Monthly restore test scheduled (first Monday of each month)
- [ ] `scripts/verify_backup.sh` tested on a backup file

```bash
# Enable backup timer
sudo cp deploy/backup.timer deploy/backup.service /etc/systemd/system/contaneta-backup.*
sudo systemctl daemon-reload && sudo systemctl enable --now contaneta-backup.timer
```

---

## 8. Monitoring

See [MONITORING.md](MONITORING.md) for detailed options.

- [ ] Health endpoint polled every 60s (`/health` and `/ready`)
- [ ] Alert on: health != ok, ready != true, backup missing > 36h
- [ ] Log rotation configured for `/var/log/contaneta/`
- [ ] WAL file size checked (alert if > 50MB)

---

## 9. LFPDPPP Compliance

See [lfpdppp_compliance_audit.md](lfpdppp_compliance_audit.md) for full audit.

- [ ] Privacy notice page live at `/privacidad` (or linked in footer)
- [ ] Registration consent checkbox implemented
- [ ] Data export endpoint working: `GET /api/account/my-data`
- [ ] Deletion request endpoint working: `POST /api/account/delete-request`
- [ ] DPO email designated and published

---

## 10. Performance

- [ ] Run `scripts/perf_audit.py` — verify no table > 1GB, no missing critical indexes
- [ ] Consider applying `migrations/040_add_performance_indexes.sql.example` if query latency observed
- [ ] WAL checkpoint cron active

---

## 11. CI / Code Quality

- [ ] `.github/workflows/ci.yml` active (lint + test on push)
- [ ] `.pre-commit-config.yaml` installed locally (`pre-commit install`)
- [ ] `ruff check` passes with zero errors
- [ ] All tests pass: `.venv/bin/pytest -q` (currently 64 tests)

---

## 12. Docker (Optional)

```bash
docker compose up -d      # web + worker
docker compose logs -f web # verify startup
curl http://localhost:8000/health
```

---

## Final Sign-Off

| Area | Owner | Date | Status |
|------|-------|------|--------|
| Security audits | — | 2026-05-12 | Complete |
| Environment config | — | — | Pending |
| Deploy + smoke tests | — | — | Pending |
| Backups verified | — | — | Pending |
| LFPDPPP basics | — | 2026-05-12 | Phase 1 complete |
| Monitoring active | — | — | Pending |
