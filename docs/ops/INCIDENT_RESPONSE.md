# Incident Response Runbook — ContaNeta

Quick-reference for on-call engineers when production incidents occur.

---

## 1. Triage (first 5 minutes)

1. **Confirm the alert**: Check `/health` and `/ready` endpoints.
   ```bash
   curl -sf https://YOUR_DOMAIN.com/health | python3 -m json.tool
   curl -sf -o /dev/null -w '%{http_code}' https://YOUR_DOMAIN.com/ready
   ```
2. **Classify severity**:
   - **P1 (critical)**: Site fully down, data loss risk, security breach → all hands.
   - **P2 (major)**: Core feature broken (invoicing, login), degraded perf → primary on-call.
   - **P3 (minor)**: Non-critical feature broken, cosmetic issue → next business day.
3. **Notify stakeholders** via agreed channel (Slack/WhatsApp).

---

## 2. Common Scenarios

### 2.1 Site unreachable (502/503/timeout)

```bash
# Check if process is running
ssh prod 'systemctl status conta-invoicing'
# Check logs
ssh prod 'journalctl -u conta-invoicing --since "10 min ago" --no-pager | tail -50'
# Restart if needed
ssh prod 'sudo systemctl restart conta-invoicing'
# Verify
curl -sf https://YOUR_DOMAIN.com/health
```

**Root causes**: OOM kill, uncaught exception on startup, disk full, Caddy/Nginx down.

### 2.2 Database locked / slow queries

```bash
# Check disk space
ssh prod 'df -h /path/to/app'
# Check DB file size and WAL
ssh prod 'ls -lh invoicing.db invoicing.db-wal invoicing.db-shm'
# Check for long-running queries (WAL checkpoint)
ssh prod 'sqlite3 invoicing.db "PRAGMA wal_checkpoint(TRUNCATE);"'
```

**Mitigation**: The app uses retry-on-lock (3 attempts, exponential backoff). If persistent:
1. Restart the app (releases all connections).
2. If WAL file is very large (>100MB), run checkpoint manually.
3. Check if gunicorn has >1 worker (`-w 1 --threads 4` is required for SQLite).

### 2.3 Invoice stamping failures

```bash
# Check Facturapi status
curl -sf https://www.facturapi.io/status
# Check recent errors in logs
ssh prod 'journalctl -u conta-invoicing --since "30 min ago" | grep -i facturapi'
```

**Common causes**: Facturapi outage, expired API key, invalid customer data (RFC, zip).
**Mitigation**: Facturapi outages resolve themselves. For API key issues, check `/admin/ops`.

### 2.4 SAT sync failures

```bash
# Check PHP availability
ssh prod 'which php && php -v'
# Check FIEL credentials
ssh prod 'ls -la storage/credentials/'
# Check cron
ssh prod 'crontab -l | grep sat'
# Manual sync test
ssh prod 'cd /path/to/app && bash sat_sync/cron_sat_sync.sh'
```

**Common causes**: PHP not installed, FIEL certificate expired, SAT portal down.

### 2.5 Disk full

```bash
ssh prod 'df -h'
ssh prod 'du -sh storage/ backup/ invoicing.db*'
```

**Mitigation**:
1. Remove old backups: `ls -lt backup/ | tail -n +6 | xargs rm -f`
2. Compress old XML: `find storage/xml -name "*.xml" -mtime +90 -exec gzip {} \;`
3. `/health` shows `disk_free_mb` and `disk_ok` (warns below 500MB).

### 2.6 Security incident (unauthorized access)

1. **Contain**: Disable the compromised account immediately.
   ```sql
   UPDATE users SET active = 0 WHERE id = ?;
   DELETE FROM sessions WHERE user_id = ?;
   ```
2. **Investigate**: Check audit log for suspicious actions.
   ```sql
   SELECT * FROM audit_log WHERE user_id = ? ORDER BY created_at DESC LIMIT 50;
   ```
3. **Rotate credentials**: SESSION_SECRET, Stripe keys, Facturapi keys, FIEL passwords.
4. **Notify affected users** per LFPDPPP requirements.

---

## 3. Rollback Procedure

If a deploy caused the incident:

```bash
# Find the previous good commit
ssh prod 'cd /path/to/app && git log --oneline -5'
# Rollback
ssh prod 'cd /path/to/app && git checkout <previous-good-commit>'
ssh prod 'sudo systemctl restart conta-invoicing'
# Verify
curl -sf https://YOUR_DOMAIN.com/health
```

**Important**: Migrations are forward-only. If a migration caused the issue, you may need to restore from backup. See `docs/ops/RECOVERY_PLAYBOOK.md`.

---

## 4. Post-Incident

1. **Timeline**: Document what happened, when, and what was done.
2. **Root cause**: Identify the underlying issue.
3. **Action items**: Preventive measures to avoid recurrence.
4. **Communicate**: Update stakeholders on resolution and follow-up.

Save post-mortems in `docs/ops/postmortems/` with format `YYYY-MM-DD-title.md`.

---

## 5. Useful Commands

| Task | Command |
|------|---------|
| Full smoke test | `BASE_URL=https://DOMAIN bash scripts/smoke_prod.sh` |
| DB integrity check | `sqlite3 invoicing.db "PRAGMA integrity_check;"` |
| View recent audit log | `sqlite3 invoicing.db "SELECT * FROM audit_log ORDER BY created_at DESC LIMIT 20;"` |
| Check active sessions | `sqlite3 invoicing.db "SELECT COUNT(*) FROM sessions WHERE expires_at > datetime('now');"` |
| Force WAL checkpoint | `sqlite3 invoicing.db "PRAGMA wal_checkpoint(TRUNCATE);"` |
| Backup now | `bash scripts/backup_db.sh && bash scripts/backup_storage.sh` |
| View worker status | `systemctl status conta-worker` |
| Process stuck jobs | `python worker.py --once` |

---

## 6. Contacts & Escalation

| Role | Contact |
|------|---------|
| Primary on-call | (configure in team settings) |
| Infrastructure | (configure in team settings) |
| SAT/Fiscal | (configure in team settings) |

---

*See also: `RECOVERY_PLAYBOOK.md`, `ROLLBACK.md`, `OPERATIONS.md`, `MONITORING.md`*
