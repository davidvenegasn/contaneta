# Launch Checklist — ContaNeta

> Step-by-step operational checklist for going to production.

---

## 1. Environment Variables

### Mandatory

```bash
# Core
ENV=prod
SESSION_SECRET=<generate: python3 -c "import secrets; print(secrets.token_hex(32))">
APP_DB_PATH=/var/data/contaneta/invoicing.db
SITE_URL=https://app.contaneta.com
DEV_MODE=0
ALLOW_DEMO_PORTAL=0
COOKIE_SECURE=1

# Email (required for password reset, verification)
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USER=noreply@contaneta.com
SMTP_PASSWORD=<app-specific-password>
SMTP_FROM=noreply@contaneta.com
```

### Billing (if Stripe enabled)

```bash
STRIPE_SECRET_KEY=sk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...
STRIPE_PRICE_ID=price_...
```

### SAT Integration

```bash
# Master key for FIEL encryption at rest (auto-derived from SESSION_SECRET if not set)
# Recommended: set explicitly for key rotation independence
AT_REST_MASTER_KEY=<64-char hex>
```

### OAuth (optional)

```bash
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
```

### Verify

```bash
# Quick check: all required vars are set
python3 -c "import config; print(f'ENV={config.ENV} PROD={config.IS_PROD} DEV={config.DEV_MODE}')"
# Expected: ENV=prod PROD=True DEV=False
```

---

## 2. Deploy Steps

### First Deploy

```bash
# 1. Clone and setup
git clone <repo> /opt/contaneta
cd /opt/contaneta
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 2. Environment
cp .env.example .env
# Edit .env with production values (see section 1)

# 3. Create directories
mkdir -p storage keys backup
chmod 700 keys

# 4. Database: migrations run automatically on app startup
# To run manually:
.venv/bin/python -c "from migrations_runner import apply_migrations; apply_migrations()"

# 5. Verify
.venv/bin/python -c "import config; print('OK:', config.ENV)"

# 6. Start (development/test)
.venv/bin/uvicorn app:app --host 0.0.0.0 --port 8000

# 7. Start (production via systemd)
sudo cp deploy/conta-invoicing.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now conta-invoicing
```

### Subsequent Deploys

```bash
cd /opt/contaneta
git pull origin main

# Migrations run automatically on restart
sudo systemctl restart conta-invoicing

# Verify
curl -s http://localhost:8000/health | python3 -m json.tool
curl -s http://localhost:8000/ready | python3 -m json.tool
```

### Reverse Proxy (Caddy — recommended)

```bash
sudo cp deploy/Caddyfile.example /etc/caddy/Caddyfile
# Edit: replace domain, paths
sudo systemctl reload caddy
```

---

## 3. Cron / Jobs

### Worker (continuous)

```bash
# Option A: systemd service (recommended)
# Create /etc/systemd/system/contaneta-worker.service:
# [Service]
# ExecStart=/opt/contaneta/.venv/bin/python /opt/contaneta/worker.py --loop
# Restart=always

# Option B: cron (every minute)
* * * * * cd /opt/contaneta && .venv/bin/python worker.py --once >> /var/log/contaneta-worker.log 2>&1
```

### SAT Sync (periodic)

```bash
# Every 6 hours: sync issued + received CFDIs for all active issuers
0 */6 * * * cd /opt/contaneta && bash sat_sync/cron_sat_sync.sh >> /var/log/sat-sync.log 2>&1
```

### Backups

```bash
# Daily at 2am: full backup (DB + storage manifest)
0 2 * * * cd /opt/contaneta && bash scripts/backup_db.sh >> /var/log/contaneta-backup.log 2>&1

# Weekly: full storage backup (XMLs)
0 3 * * 0 cd /opt/contaneta && bash scripts/backup_storage.sh >> /var/log/contaneta-backup-storage.log 2>&1
```

### WAL Checkpoint (prevent .db-wal bloat)

```bash
# Every 4 hours
0 */4 * * * sqlite3 /var/data/contaneta/invoicing.db 'PRAGMA wal_checkpoint(TRUNCATE);' >> /var/log/contaneta-wal.log 2>&1
```

---

## 4. Backup / Restore

### Backup

```bash
# Quick DB backup (hot, safe with WAL mode)
bash scripts/backup_db.sh
# Output: backup/invoicing_YYYYMMDD_HHMMSS.db

# Full backup (DB + XML storage)
bash scripts/backup_all.sh
```

### Restore

```bash
# 1. Stop the service
sudo systemctl stop conta-invoicing

# 2. Backup current DB (safety)
cp /var/data/contaneta/invoicing.db /var/data/contaneta/invoicing.db.pre-restore

# 3. Restore from backup
cp backup/invoicing_20260301_020000.db /var/data/contaneta/invoicing.db

# 4. Delete WAL artifacts (they belong to the old DB state)
rm -f /var/data/contaneta/invoicing.db-wal /var/data/contaneta/invoicing.db-shm

# 5. Restart
sudo systemctl start conta-invoicing

# 6. Verify
curl -s http://localhost:8000/health
```

### Off-site Backup

```bash
# Rsync to remote
rsync -avz backup/ user@backup-server:/backups/contaneta/

# Or S3
aws s3 sync backup/ s3://contaneta-backups/$(date +%Y%m%d)/
```

---

## 5. Smoke Tests

### Quick (no auth needed)

```bash
BASE_URL=https://app.contaneta.com

# Health
curl -sf "$BASE_URL/health" | python3 -c "import sys,json; d=json.load(sys.stdin); assert d['status']=='ok', f'FAIL: {d}'; print('OK: health')"

# Ready
curl -sf "$BASE_URL/ready" | python3 -c "import sys,json; d=json.load(sys.stdin); assert d['ready']==True, f'FAIL: {d}'; print('OK: ready')"

# Status page renders
curl -sf -o /dev/null -w '%{http_code}' "$BASE_URL/status" | grep -q 200 && echo "OK: status"

# Login page renders
curl -sf -o /dev/null -w '%{http_code}' "$BASE_URL/login" | grep -q 200 && echo "OK: login page"

# API without auth returns 401
curl -sf -o /dev/null -w '%{http_code}' "$BASE_URL/api/customers" | grep -q 401 && echo "OK: API auth enforced"
```

### Full (with auth — use smoke_release.sh)

```bash
bash scripts/smoke_release.sh
```

---

## 6. Monitoring

### Endpoints to Poll

| Endpoint | Expected | Frequency | Alert if |
|----------|----------|-----------|----------|
| `GET /health` | `{"status":"ok"}` | 1 min | status != "ok" |
| `GET /ready` | `{"ready":true}` | 1 min | ready != true or 503 |

### Log Files

| File | Content |
|------|---------|
| systemd journal | App stdout/stderr (gunicorn + FastAPI) |
| `/var/log/contaneta-worker.log` | Job worker output |
| `/var/log/sat-sync.log` | SAT sync cron output |
| `/var/log/contaneta-backup.log` | Backup script output |

### Database Health

```bash
# Check WAL file size (should stay < 50 MB)
ls -lh /var/data/contaneta/invoicing.db-wal

# Check DB size
ls -lh /var/data/contaneta/invoicing.db

# Check active jobs
sqlite3 /var/data/contaneta/invoicing.db "SELECT status, COUNT(*) FROM jobs GROUP BY status;"

# Check failed jobs
sqlite3 /var/data/contaneta/invoicing.db "SELECT id, name, error_json FROM jobs WHERE status='failed' ORDER BY updated_at DESC LIMIT 5;"
```
