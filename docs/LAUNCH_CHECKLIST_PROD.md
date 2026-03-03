# Launch Checklist — Production

## Pre-Deploy

- [ ] All tests pass: `.venv/bin/pytest -q`
- [ ] Smoke tests pass locally: `bash scripts/smoke_release.sh`
- [ ] `.env.example` is up to date with all required variables
- [ ] No `DEV_MODE=1` in production `.env`
- [ ] `SESSION_SECRET` is set (random hex, 32+ bytes)
- [ ] `AT_REST_MASTER_KEY` is set (random hex, 32+ bytes)
- [ ] `ADMIN_PASSWORD` is set for `/admin` basic auth
- [ ] No hardcoded secrets in code (`grep -r "sk_live\|password.*=" --include="*.py"`)
- [ ] Git status clean on release branch

## Infrastructure

- [ ] VPS provisioned (Ubuntu 22.04/24.04, 2GB+ RAM)
- [ ] DNS A record points to VPS IP
- [ ] Firewall configured (UFW: 22, 80, 443 only)
- [ ] Nginx installed and configured (`deploy/nginx/contaneta.conf`)
- [ ] SSL certificate installed via `certbot --nginx`
- [ ] PHP installed with required extensions (`php -m | grep -E "curl|xml|mbstring|sqlite3"`)

## Application

- [ ] Code deployed to `/opt/contaneta`
- [ ] `.venv` created and dependencies installed
- [ ] `.env` configured with all production values
- [ ] Migrations run successfully (auto on startup)
- [ ] `storage/` directories exist with correct permissions
- [ ] `logs/` directory exists

## Services

- [ ] `contaneta-web.service` enabled and running
- [ ] `contaneta-sat-worker.service` enabled and running
- [ ] `contaneta-sat-scheduler.timer` enabled and active
- [ ] `contaneta-backup.timer` enabled and active
- [ ] All services auto-restart on failure (`systemctl status`)

## Verification

- [ ] `curl https://DOMAIN/health` returns `{"status": "ok"}`
- [ ] Login page loads at `https://DOMAIN/login`
- [ ] Registration works end-to-end
- [ ] Can create an invoice
- [ ] SAT credential upload works
- [ ] SAT sync runs successfully after credential upload
- [ ] `/admin` requires authentication (returns 401 without)
- [ ] `/admin` dashboard loads with correct stats
- [ ] Smoke test passes: `BASE_URL=https://DOMAIN bash scripts/smoke_release.sh`

## Monitoring

- [ ] Sentry configured (optional): `SENTRY_DSN` in `.env`
- [ ] Log rotation configured (`/etc/logrotate.d/contaneta`)
- [ ] Backup runs nightly (check `systemctl list-timers contaneta-backup.timer`)
- [ ] Test backup restore: `sqlite3 /opt/contaneta/backups/latest.db ".tables"`

## Stripe (if billing enabled)

- [ ] `STRIPE_SECRET_KEY` is `sk_live_*` (not test key)
- [ ] `STRIPE_WEBHOOK_SECRET` configured
- [ ] Webhook endpoint registered in Stripe dashboard (`/billing/webhook`)
- [ ] Test subscription flow end-to-end

## Post-Launch (first 24h)

- [ ] Monitor `/admin/errors` for 5xx errors
- [ ] Check `/admin/jobs` for failed jobs
- [ ] Verify SAT scheduler is enqueuing jobs (`/admin/jobs` shows sat_refresh_light)
- [ ] Check backup ran successfully: `ls -la /opt/contaneta/backups/`
- [ ] Review access logs for anomalies: `tail -100 /opt/contaneta/logs/access.log`
