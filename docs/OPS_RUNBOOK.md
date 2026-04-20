# Operations Runbook — ContaNeta

## Quick Reference

| Action | Command |
|--------|---------|
| Start server | `systemctl start contaneta-web` |
| Stop server | `systemctl stop contaneta-web` |
| Restart | `systemctl restart contaneta-web contaneta-sat-worker` |
| View logs | `journalctl -u contaneta-web -f` or `tail -f /var/log/contaneta/web.log` |
| Health check | `curl -s http://localhost:8000/health \| jq` |
| Readiness | `curl -s http://localhost:8000/ready` |
| Run tests | `.venv/bin/pytest -q` |
| Backup DB | `bash scripts/backup_db.sh` |
| Backup storage | `bash scripts/backup_storage.sh` |
| Backup all | `bash scripts/backup_all.sh` |
| Process SAT jobs | `python scripts/sat_worker.py` |
| SAT auto-sync scheduler | `python scripts/sat_scheduler.py --batch 50` |
| Process generic jobs | `python worker.py --once` |
| Run migrations | Automatic on startup; or `python -c "from migrations_runner import apply_migrations; apply_migrations()"` |

---

## Production Mode (recommended)

**Gunicorn**: 1 worker + 4 threads (SQLite limitation — no concurrent writers).

```bash
gunicorn app:app -k uvicorn.workers.UvicornWorker -w 1 --threads 4 -b 127.0.0.1:8000
```

**Directory layout** (data outside the repo):

| Path | Contents |
|------|----------|
| `/opt/contaneta/` | Application code (git repo) |
| `/var/lib/contaneta/invoicing.db` | SQLite database (`APP_DB_PATH`) |
| `/var/lib/contaneta/storage/` | XML files, encrypted creds (`APP_STORAGE_PATH`) |
| `/var/log/contaneta/` | Application + access logs |
| `/var/backups/contaneta/` | Nightly backups (`BACKUP_DIR`) |

**Reverse proxy**: Caddy (automatic HTTPS) or Nginx + certbot.

**Services**: See `deploy/systemd/` for service files and `deploy/README_DEPLOY.md` for full setup.

**Bootstrap**: `sudo bash scripts/prod_bootstrap.sh` sets up user, dirs, venv, logrotate, firewall.

---

## 1. Health Checks

### Endpoints

| Endpoint | Purpose | Response |
|----------|---------|----------|
| `GET /health` | Full system health | JSON: `db_readable`, `migrations_applied`, `storage_ok`, `pdfplumber_ok` |
| `GET /ready` | Load balancer probe | 200 OK or 503 Service Unavailable |
| `GET /status` | Admin HTML overview | System state + Support Snapshot |

### Automated Monitoring

```bash
# Simple uptime check (add to monitoring tool)
curl -sf http://localhost:8000/ready || echo "ALERT: ContaNeta is down"

# Health with details
curl -s http://localhost:8000/health | python3 -c "
import json, sys
h = json.load(sys.stdin)
if not all([h.get('db_readable'), h.get('migrations_applied'), h.get('storage_ok')]):
    print('UNHEALTHY:', h)
    sys.exit(1)
print('OK')
"
```

---

## 2. Logging

### Configuration

| Env Variable | Default | Purpose |
|-------------|---------|---------|
| `LOG_LEVEL` | `INFO` | Python log level |
| `LOG_FILE` | (none) | Write logs to file (in addition to stderr) |
| `LOG_FORMAT` | `%(asctime)s ...` | Python log format string |
| `LOG_REQUESTS` | `1` | Log HTTP method/path/status/duration |
| `LOG_REQUEST_ID` | `1` | Include X-Request-ID in response headers |

### Log Format

```
2026-01-15 10:30:00 [a1b2c3d4e5f6] INFO: POST /api/invoices/quick 200 1.234s
```

Every log line includes the request ID (`[a1b2c3d4e5f6]`), which can be used to trace a request across all log entries.

### Log Sources

| Source | Content |
|--------|---------|
| App (uvicorn/gunicorn) | Request logs, errors, startup messages |
| Action log (`services/action_log.py`) | Structured one-line events: `action=login user_id=5` |
| Audit log (`services/audit.py`) | Database-persisted: login, impersonation, credential upload |
| Error events (`services/error_events.py`) | Captured exceptions with redacted tracebacks |
| SAT worker | SAT sync job status (ok/error per job) |

### Viewing Logs

```bash
# Live server logs (systemd)
journalctl -u conta-invoicing -f

# Filter by request ID
journalctl -u conta-invoicing | grep "a1b2c3d4e5f6"

# Error events in DB
sqlite3 invoicing.db "SELECT created_at, request_id, path, message_public FROM error_events ORDER BY created_at DESC LIMIT 20;"

# Audit trail
sqlite3 invoicing.db "SELECT created_at, action, user_id, issuer_id, details FROM audit_log ORDER BY created_at DESC LIMIT 20;"
```

### Log Rotation

Deploy the included logrotate config:

```bash
sudo cp deploy/logrotate-conta.example /etc/logrotate.d/conta-invoicing
# Edit paths in the file to match your installation
```

---

## 3. Backups

### Database Backup

Uses `sqlite3 .backup` for WAL-safe snapshots:

```bash
# Manual
bash scripts/backup_db.sh

# Output: backup/invoicing_YYYYMMDD_HHMMSS.db.gz
# Retention: deletes backups older than BACKUP_RETAIN_DAYS (default 30)
```

### Storage Backup

Backs up XML, credentials (encrypted), bank statements, exports:

```bash
bash scripts/backup_storage.sh

# Output: backup/storage_YYYYMMDD_HHMMSS.tar.gz
# Excludes: temp files, caches, raw .cer/.key (only .enc kept)
```

### Crontab Setup

```crontab
# Database backup daily at 2 AM
0 2 * * * cd /path/to/project && bash scripts/backup_db.sh >> /tmp/backup.log 2>&1

# Storage backup weekly (Sunday 3 AM)
0 3 * * 0 cd /path/to/project && bash scripts/backup_storage.sh >> /tmp/backup.log 2>&1

# SAT sync every 15 min (legacy direct sync)
*/15 * * * * /path/to/project/sat_sync/cron_sat_sync.sh >> /tmp/sat_sync.log 2>&1

# SAT auto-sync scheduler every 10 min (enqueues jobs for eligible issuers)
*/10 * * * * cd /path/to/project && .venv/bin/python scripts/sat_scheduler.py --batch 50 --cooldown-hours 8 >> /tmp/sat_scheduler.log 2>&1

# SAT job queue every 2 min (processes enqueued jobs)
*/2 * * * * cd /path/to/project && .venv/bin/python scripts/sat_worker.py >> /tmp/sat_worker.log 2>&1
```

### Restore Procedure

```bash
# 1. Stop the server
sudo systemctl stop conta-invoicing

# 2. Restore database
gunzip -k backup/invoicing_YYYYMMDD_HHMMSS.db.gz
cp backup/invoicing_YYYYMMDD_HHMMSS.db invoicing.db

# 3. Restore storage (if needed)
tar xzf backup/storage_YYYYMMDD_HHMMSS.tar.gz -C storage/

# 4. Start the server (migrations run automatically)
sudo systemctl start conta-invoicing

# 5. Verify
curl -s http://localhost:8000/health | jq
```

### Off-site Backup

```bash
# Example: copy to S3 after backup
aws s3 cp backup/invoicing_$(date +%Y%m%d)*.db.gz s3://your-bucket/backups/db/
aws s3 cp backup/storage_$(date +%Y%m%d)*.tar.gz s3://your-bucket/backups/storage/
```

---

## 4. Admin Panel

Access: `https://your-domain/admin/` (HTTP Basic Auth)

### Required Environment

```bash
ADMIN_PASSWORD=your-strong-password  # Required for admin access
```

### Key Admin Pages

| Page | URL | Shows |
|------|-----|-------|
| Dashboard | `/admin/` | User/issuer counts, recent logins, job status, CFDI stats |
| Users | `/admin/users` | All users with roles |
| Issuers | `/admin/issuers` | All companies with subscription status |
| Issuer Detail | `/admin/issuers/{id}` | Notes, needs_review flag, force-sync button |
| Jobs | `/admin/jobs` | Job queue with status filters |
| Errors | `/admin/errors` | Error events with traceback |
| Memberships | `/admin/memberships` | User-issuer-role matrix |
| Ops Console | `/admin/ops` | Run migrations, trigger backups |
| Health | `/admin/health` | System overview |

### Impersonation

Admin can impersonate any issuer for debugging:

```
POST /admin/impersonate/<issuer_id>
```

This creates a 4-part session cookie with `restore_issuer_id`. All actions during impersonation are audit-logged. End impersonation via the topbar "stop impersonating" button.

---

## 5. Common Operations

### Add a New Issuer

Users self-register via `/signup`. The registration flow:
1. Creates user account (bcrypt password)
2. Creates issuer (initially with RFC="PENDIENTE")
3. Creates membership (role=owner)
4. User completes profile at `/confirmar-perfil`

### Reset a User's Password

```bash
# Via admin console or direct DB (generates temporary token)
sqlite3 invoicing.db "
INSERT INTO password_resets (user_id, token_hash, created_at, expires_at)
VALUES (
  (SELECT id FROM users WHERE email='user@example.com'),
  '<sha256-hash>',
  datetime('now'),
  datetime('now', '+2 hours')
);
"
# Better: user uses /forgot flow (self-service)
```

### Deactivate an Issuer

```bash
sqlite3 invoicing.db "UPDATE issuers SET active = 0 WHERE id = <issuer_id>;"
```

Deactivated issuers cannot be selected during login (filtered by `active = 1`).

### Check SAT Sync Status

```bash
# Recent SAT jobs
sqlite3 invoicing.db "SELECT id, issuer_id, direction, status, finished_at, last_error FROM sat_jobs ORDER BY id DESC LIMIT 10;"

# SAT sync state per issuer
sqlite3 invoicing.db "SELECT issuer_id, last_sync_at, status, message FROM sat_sync_state ORDER BY last_sync_at DESC;"
```

### Clear Stuck Jobs

```bash
# Generic jobs stuck in 'running' (worker crashed)
sqlite3 invoicing.db "UPDATE jobs SET status='queued', locked_by=NULL, locked_at=NULL WHERE status='running' AND datetime(locked_at) < datetime('now', '-30 minutes');"

# SAT jobs stuck in 'running'
sqlite3 invoicing.db "UPDATE sat_jobs SET status='queued', locked_at=NULL WHERE status='running' AND datetime(locked_at) < datetime('now', '-30 minutes');"
```

---

## 6. Incident Response

### Server Won't Start

```bash
# Check logs
journalctl -u conta-invoicing --no-pager -n 50

# Common causes:
# 1. Missing SESSION_SECRET in prod
#    Fix: Set SESSION_SECRET in .env (64-char hex)
# 2. Missing SITE_URL
#    Fix: Set SITE_URL=https://your-domain.com
# 3. Database locked
#    Fix: Check for zombie processes: lsof invoicing.db
# 4. Port already in use
#    Fix: lsof -i :8000
```

### High Error Rate

```bash
# Check recent errors
sqlite3 invoicing.db "SELECT created_at, path, message_public, request_id FROM error_events WHERE created_at > datetime('now', '-1 hour') ORDER BY created_at DESC;"

# Group by path to find hot spots
sqlite3 invoicing.db "SELECT path, COUNT(*) as cnt FROM error_events WHERE created_at > datetime('now', '-1 hour') GROUP BY path ORDER BY cnt DESC LIMIT 10;"
```

### Database Too Large

```bash
# Check size
ls -lh invoicing.db

# Check table sizes
sqlite3 invoicing.db "SELECT name, SUM(pgsize) as size FROM dbstat GROUP BY name ORDER BY size DESC LIMIT 10;"

# Vacuum (reclaim space — takes a lock, do during maintenance)
sqlite3 invoicing.db "VACUUM;"
```

### Session Issues

```bash
# If SESSION_SECRET was rotated, all sessions are invalidated
# Users must log in again — this is expected behavior

# Check if password_changed_at is causing session invalidation
sqlite3 invoicing.db "SELECT id, email, password_changed_at FROM users WHERE password_changed_at IS NOT NULL ORDER BY password_changed_at DESC LIMIT 10;"
```

---

## 7. Worker (SAT Sync + Jobs)

### Service

```bash
# Start/stop/restart
sudo systemctl start conta-worker
sudo systemctl stop conta-worker
sudo systemctl restart conta-worker

# View logs
journalctl -u conta-worker -f

# Status
systemctl status conta-worker
```

Service file: `deploy/conta-worker.service`

### How it works

The worker runs in a continuous loop (`worker.py --loop --sleep=2`):

1. **Job processor**: Claims and executes queued jobs (SAT sync, verify, backfill)
2. **Scheduler** (every 5 min): Checks which issuers need a SAT refresh (cooldown expired), enqueues `sat_refresh_light` jobs
3. **XML backfill** (every 6 hours): Finds CFDIs missing XML files, enqueues `sat_xml_backfill` jobs to retry downloads

### Job types

| Job | What it does | Timeout |
|-----|-------------|---------|
| `sat_refresh_light` | Sync metadata + download XMLs for current month | 600s |
| `sat_sync_month` | Sync a specific month+direction | 600s |
| `sat_verify_credentials` | Validate FIEL is correct | 30s |
| `sat_xml_backfill` | Retry XML download for CFDIs missing xml_path | 600s |

### Tuning

| Env Variable | Default | Purpose |
|-------------|---------|---------|
| `SAT_SYNC_COOLDOWN_SECONDS` | `7200` (2h) | Time between syncs per issuer |
| `SAT_SCHEDULER_INTERVAL` | `300` (5 min) | How often scheduler checks for eligible issuers |
| `SAT_BACKFILL_INTERVAL` | `21600` (6h) | How often backfill scheduler runs |
| `JOB_TIMEOUT_SECONDS` | `600` (10 min) | Max time per job before timeout |
| `JOB_LEASE_SECONDS` | `900` (15 min) | Lease lock duration |

### Troubleshooting

**Worker not processing jobs:**
```bash
# Check if running
systemctl status conta-worker

# Check for stuck jobs
sqlite3 invoicing.db "SELECT id, name, status, locked_at FROM jobs WHERE status = 'running' ORDER BY id DESC LIMIT 5;"

# Reset stuck jobs (if worker crashed)
sqlite3 invoicing.db "UPDATE jobs SET status='queued', locked_by=NULL, locked_at=NULL WHERE status='running' AND datetime(locked_at) < datetime('now', '-30 minutes');"
```

**SAT sync failing for an issuer:**
```bash
# Check last error
sqlite3 invoicing.db "SELECT issuer_id, direction, last_error, last_attempt_at FROM sat_sync_state WHERE last_error IS NOT NULL;"

# Check FIEL validity
sqlite3 invoicing.db "SELECT issuer_id, validation_ok, validation_message FROM sat_credentials;"

# Force re-sync via admin panel or enqueue directly
sqlite3 invoicing.db "INSERT INTO jobs (name, issuer_id, payload_json, status) VALUES ('sat_refresh_light', <ISSUER_ID>, '{\"issuer_id\": <ISSUER_ID>}', 'queued');"
```

---

## 8. Incident Playbooks

### SAT service unavailable

1. Check `sat_sync_state.last_error` for SAT error messages
2. SAT web service outages are common — jobs auto-retry with exponential backoff (up to 10 min)
3. If persistent: check SAT status at https://www.sat.gob.mx/
4. The worker will resume automatically when SAT comes back

### Database locked

```bash
# Find what's holding the lock
lsof invoicing.db
fuser invoicing.db

# If zombie process:
kill <PID>

# Force WAL checkpoint (after killing zombie)
sqlite3 invoicing.db "PRAGMA wal_checkpoint(TRUNCATE);"

# Restart services
sudo systemctl restart conta-invoicing conta-worker
```

### Storage full

```bash
# Check disk usage
df -h /
du -sh storage/*
du -sh backup/*

# Clean old backups (keep last 7 days)
find backup/ -name "invoicing_*.db*" -mtime +7 -delete
find backup/ -name "storage_*.tar.gz" -mtime +7 -delete

# Clean old XML files (rarely needed — these are small)
du -sh storage/xml/

# Vacuum database (reclaims space, takes a brief lock)
sqlite3 invoicing.db "VACUUM;"
```

### Backup verification

```bash
# Non-destructive drill — verifies integrity + prints row counts
bash scripts/backup_verify.sh

# Full restore drill (uses temp copy, does NOT affect live DB)
# See scripts/restore_latest.sh for production restore procedure
```

---

## 9. Environment Variables

| Variable | Required (Prod) | Purpose |
|----------|----------------|---------|
| `ENV` | Yes | `prod` for production |
| `SESSION_SECRET` | **Yes** | Cookie signing (64-char hex) |
| `SITE_URL` | **Yes** | Base URL for redirects/callbacks |
| `APP_DB_PATH` | No | SQLite path (default: `./invoicing.db`) |
| `ADMIN_PASSWORD` | **Yes** | Admin panel access |
| `AT_REST_MASTER_KEY` | **Yes** | Encryption master key (32 bytes hex). App won't start without it in prod. |
| `LOG_LEVEL` | No | `INFO` (default) |
| `LOG_FILE` | No | Path for file logging |
| `BACKUP_DIR` | No | Backup output directory |
| `BACKUP_RETAIN_DAYS` | No | Backup retention (default 30) |
| `STRIPE_SECRET_KEY` | If billing | Stripe API key |
| `STRIPE_WEBHOOK_SECRET` | If billing | Stripe webhook signing secret |

---

## 10. Deployment Checklist

See also: `docs/LAUNCH_CHECKLIST.md`

Pre-deploy:
- [ ] `.env` configured with production values
- [ ] `SESSION_SECRET` is a unique 64-char hex string
- [ ] `ADMIN_PASSWORD` is strong (20+ chars)
- [ ] `AT_REST_MASTER_KEY` set (required — app won't start without it)
- [ ] Backups configured (cron)
- [ ] Log rotation configured
- [ ] SSL/TLS configured (Caddy/Nginx)
- [ ] Firewall rules (only 80/443 exposed)

Post-deploy:
- [ ] `/health` returns all green
- [ ] `/ready` returns 200
- [ ] Login works
- [ ] Admin panel accessible
- [ ] SAT sync cron running
- [ ] Backup cron running
