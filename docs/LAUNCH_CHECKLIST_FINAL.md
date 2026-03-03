# Launch Checklist Final — v0.1.0

## A) Variables .env requeridas

Copy to `/var/lib/contaneta/.env` and fill with real values:

```bash
# ── Core (REQUIRED) ──
ENV=prod
SESSION_SECRET=<python3 -c "import secrets; print(secrets.token_hex(32))">
AT_REST_MASTER_KEY=<python3 -c "import secrets; print(secrets.token_hex(32))">
APP_DB_PATH=/var/lib/contaneta/invoicing.db
SITE_URL=https://YOUR_DOMAIN.com

# ── Storage paths ──
APP_STORAGE_PATH=/var/lib/contaneta/storage
BACKUP_DIR=/var/backups/contaneta
LOG_FILE=/var/log/contaneta/app.log

# ── Stripe (if billing enabled) ──
STRIPE_SECRET_KEY=sk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...
STRIPE_PRICE_ID=price_...

# ── Facturapi (if CFDI stamping enabled) ──
FACTURAPI_API_KEY=...

# ── SAT sync ──
PHP_BIN=php
SAT_SYNC_BACKFILL_DAYS=7
SAT_SYNC_WINDOW_HOURS=6

# ── Optional ──
LOG_REQUEST_ID=1
LOG_REQUESTS=1
COOKIE_SECURE=1
DEV_MODE=0
SENTRY_DSN=
```

```bash
chmod 600 /var/lib/contaneta/.env
```

## B) Permisos en servidor

```bash
# User and ownership
sudo useradd -r -m -s /usr/sbin/nologin contaneta 2>/dev/null || true
sudo chown -R contaneta:contaneta /var/lib/contaneta
sudo chown -R contaneta:contaneta /var/log/contaneta
sudo chown -R contaneta:contaneta /var/backups/contaneta
sudo chown -R contaneta:contaneta /opt/contaneta

# Sensitive files
sudo chmod 600 /var/lib/contaneta/.env
sudo chmod 600 /var/lib/contaneta/invoicing.db
sudo chmod 700 /var/lib/contaneta/storage/credentials/
```

## C) Servicios systemd

```bash
# Copy units
sudo cp /opt/contaneta/deploy/systemd/*.service /etc/systemd/system/
sudo cp /opt/contaneta/deploy/systemd/*.timer /etc/systemd/system/

# Enable and start
sudo systemctl daemon-reload
sudo systemctl enable --now contaneta-web
sudo systemctl enable --now contaneta-sat-worker
sudo systemctl enable --now contaneta-sat-scheduler.timer
sudo systemctl enable --now contaneta-backup.timer

# Verify
sudo systemctl status contaneta-web
sudo systemctl status contaneta-sat-worker
```

## D) Timers/Cron

| Timer | Schedule | What it does |
|-------|----------|-------------|
| `contaneta-sat-scheduler.timer` | Every 10 min | Enqueues SAT sync jobs for eligible issuers |
| `contaneta-backup.timer` | Daily 02:00 | SQLite backup + storage tar, 7-day rotation |
| `contaneta-sat-worker` | Continuous | Processes sat_jobs queue (service, not timer) |

```bash
# Check timers
sudo systemctl list-timers --all | grep contaneta
```

## E) Smoke tests en prod

```bash
# Quick manual checks
curl -sf https://YOUR_DOMAIN.com/health | python3 -m json.tool
curl -sf https://YOUR_DOMAIN.com/ready  | python3 -m json.tool
curl -sf -o /dev/null -w '%{http_code}' https://YOUR_DOMAIN.com/login         # → 200
curl -sf -o /dev/null -w '%{http_code}' https://YOUR_DOMAIN.com/admin         # → 401/403
curl -sf -o /dev/null -w '%{http_code}' https://YOUR_DOMAIN.com/portal/home   # → 302

# Full smoke suite
BASE_URL=https://YOUR_DOMAIN.com bash /opt/contaneta/scripts/smoke_release.sh
```

Expected `/health` response:
```json
{
  "status": "ok",
  "db": "ok",
  "db_readable": true,
  "migrations_applied": true,
  "storage_exists": true,
  "storage_writable": true
}
```

## F) Runbook rápido — qué revisar si algo falla

### App no responde (502/504)

```bash
sudo systemctl status contaneta-web
sudo journalctl -u contaneta-web -n 50 --no-pager
curl -s http://127.0.0.1:8000/health  # bypass Caddy
```

### SAT sync no funciona

```bash
# Check worker
sudo systemctl status contaneta-sat-worker
sudo journalctl -u contaneta-sat-worker -n 30 --no-pager

# Check scheduler
sudo systemctl list-timers | grep sat-scheduler

# Triage
sudo -u contaneta bash /opt/contaneta/scripts/ops_triage.sh

# Check stuck jobs
sqlite3 /var/lib/contaneta/invoicing.db \
  "SELECT id, status, issuer_id, direction, locked_at FROM sat_jobs WHERE status='running';"

# Clear stuck
sqlite3 /var/lib/contaneta/invoicing.db \
  "UPDATE sat_jobs SET status='queued', locked_at=NULL WHERE status='running' AND locked_at < datetime('now', '-30 minutes');"
```

### Database issues

```bash
sqlite3 /var/lib/contaneta/invoicing.db "PRAGMA integrity_check;"
sqlite3 /var/lib/contaneta/invoicing.db "PRAGMA wal_checkpoint(TRUNCATE);"
ls -la /var/lib/contaneta/invoicing.db*  # check WAL size
```

### Restore from backup

```bash
sudo bash /opt/contaneta/scripts/restore_latest.sh
# Or specific backup:
sudo bash /opt/contaneta/scripts/restore_latest.sh invoicing_20260303_020000.db.gz
```

### Check errors

```bash
# Admin panel
open https://YOUR_DOMAIN.com/admin/errors

# CLI
sqlite3 /var/lib/contaneta/invoicing.db \
  "SELECT id, created_at, status, path, substr(message_internal,1,80) FROM error_events ORDER BY id DESC LIMIT 10;"
```

### Logs

```bash
# Web app
sudo journalctl -u contaneta-web -f
tail -f /var/log/contaneta/web.log

# Worker
sudo journalctl -u contaneta-sat-worker -f

# Access log (Caddy)
tail -f /var/log/caddy/access.log
```

---

**Version**: v0.1.0 | **Date**: 2026-03-03 | **Branch**: main
