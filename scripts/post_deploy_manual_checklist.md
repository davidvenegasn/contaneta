# Post-Deploy Manual Checklist — ContaNeta

Run through this checklist after every production deployment.

## 1. DNS & Connectivity

- [ ] Domain resolves to correct IP: `dig +short YOUR_DOMAIN`
- [ ] HTTPS loads without certificate errors: `curl -sI https://YOUR_DOMAIN`
- [ ] HTTP redirects to HTTPS (if configured)

## 2. HTTPS & SSL Certificate

- [ ] SSL certificate is valid and not expiring soon (>30 days)
- [ ] Check with: `echo | openssl s_client -connect YOUR_DOMAIN:443 2>/dev/null | openssl x509 -noout -enddate`

## 3. Health Endpoint

- [ ] `GET /health` returns `{"status": "ok"}`
- [ ] `db_readable: true`
- [ ] `migrations_applied: true`
- [ ] `disk_ok: true`
- [ ] `storage_writable: true`

## 4. Account Creation & Login

- [ ] Create a new test account via `/signup`
- [ ] Verify login works via `/login`
- [ ] Verify session cookie is set with `Secure` and `HttpOnly` flags
- [ ] Verify portal loads after login (`/portal/home`)

## 5. Password Reset

- [ ] Request password reset via `/forgot-password`
- [ ] Verify reset email is sent (check logs if no email provider configured)
- [ ] Verify reset link works and allows password change

## 6. FIEL Upload (SAT Credentials)

- [ ] Upload a test .cer + .key pair
- [ ] Verify validation succeeds (or fails gracefully with bad creds)
- [ ] Verify SAT sync can be triggered

## 7. DEV_MODE is OFF

- [ ] `/debug-oauth` returns 404 or 405 (not 200)
- [ ] Demo login links are not visible on the login page
- [ ] No debug toolbar or verbose errors shown to end users

## 8. Sentry / Error Tracking

- [ ] If `SENTRY_DSN` is configured, trigger a test error and verify it appears in Sentry
- [ ] Check Sentry dashboard for any startup errors

## 9. Backups

- [ ] Verify backup cron is configured: `crontab -l | grep backup`
- [ ] Run a manual backup: `bash scripts/backup_db.sh`
- [ ] Verify backup file was created in `backup/` directory
- [ ] Verify backup rotation is working (old backups cleaned up)

## 10. Smoke Tests

- [ ] Run automated smoke tests: `BASE_URL=https://YOUR_DOMAIN bash scripts/smoke_prod.sh`
- [ ] All checks pass (green)

## 11. Monitoring

- [ ] External uptime monitor configured (e.g., UptimeRobot, Healthchecks.io)
- [ ] Monitor points to `/health` endpoint
- [ ] Alert notifications working (email, Slack, etc.)

---

**Tip:** Run `BASE_URL=https://YOUR_DOMAIN bash scripts/smoke_prod.sh` to automate checks 1-3, 7, and parts of 10.
