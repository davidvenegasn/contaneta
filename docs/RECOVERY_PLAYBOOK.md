# Recovery Playbook

## Backup Architecture

```
/var/backups/contaneta/
├── invoicing_YYYYMMDD_HHMMSS.db.gz    # SQLite DB (gzipped)
├── storage_YYYYMMDD_HHMMSS.tar.gz     # XML/PDF files (credentials excluded)
└── pre_restore_*.db                     # Auto-saved before any restore
```

- **Schedule**: Daily via systemd timer (`contaneta-backup.timer`)
- **Retention**: 7 days by default (`BACKUP_RETENTION_DAYS`)
- **Remote**: Optional S3 via rclone (`BACKUP_RCLONE_REMOTE`)

## Scenario 1: Database Corruption

**Symptoms**: 500 errors, "database disk image is malformed", WAL checkpoint failures

```bash
# 1. Check integrity
sqlite3 /var/lib/contaneta/invoicing.db "PRAGMA integrity_check;"

# 2. If corrupted, restore from latest backup
sudo bash /opt/contaneta/scripts/restore_latest.sh

# 3. Verify
curl -s http://localhost:8000/health | python3 -m json.tool
```

## Scenario 2: Accidental Data Deletion

```bash
# 1. Stop writes immediately
sudo systemctl stop contaneta-web contaneta-worker

# 2. List available backups (newest first)
ls -lt /var/backups/contaneta/invoicing_*.db.gz

# 3. Restore specific backup
sudo bash /opt/contaneta/scripts/restore_latest.sh invoicing_20260302_020000.db.gz

# 4. Check data
sqlite3 /var/lib/contaneta/invoicing.db "SELECT COUNT(*) FROM invoices;"
```

## Scenario 3: Server Migration

```bash
# On old server:
bash /opt/contaneta/scripts/backup_nightly.sh
scp /var/backups/contaneta/invoicing_latest.db.gz new-server:/tmp/

# On new server:
bash /opt/contaneta/scripts/prod_bootstrap.sh
cp /tmp/invoicing_latest.db.gz /var/backups/contaneta/
sudo bash /opt/contaneta/scripts/restore_latest.sh
```

## Scenario 4: SAT Sync Issues / Stuck Jobs

```bash
# Triage
bash /opt/contaneta/scripts/ops_triage.sh

# Reset stuck SAT jobs
sqlite3 /var/lib/contaneta/invoicing.db \
  "UPDATE sat_jobs SET status='queued', locked_at=NULL WHERE status='running' AND locked_at < datetime('now', '-30 minutes');"

# Clear cooldowns
sqlite3 /var/lib/contaneta/invoicing.db \
  "UPDATE sat_sync_state SET cooldown_until=NULL WHERE cooldown_until IS NOT NULL;"

# Restart worker
sudo systemctl restart contaneta-worker
```

## Scenario 5: Full Disaster Recovery (New VPS)

1. Provision new VPS (Ubuntu 22.04+)
2. Run bootstrap: `bash scripts/prod_bootstrap.sh`
3. Copy `.env` from secure location
4. Copy latest backup files
5. Run restore: `bash scripts/restore_latest.sh`
6. Update DNS to new server IP
7. Verify: `curl https://app.contaneta.com/health`

## Key Paths

| What | Path |
|------|------|
| Application | `/opt/contaneta/` |
| Database | `/var/lib/contaneta/invoicing.db` |
| Storage (XML/PDF) | `/var/lib/contaneta/storage/` |
| Credentials (encrypted) | `/var/lib/contaneta/storage/credentials/` |
| Backups | `/var/backups/contaneta/` |
| Logs | `/var/log/contaneta/` |
| Environment | `/var/lib/contaneta/.env` |

## Testing Backups (Monthly Drill)

```bash
# 1. Create a test restore directory
mkdir /tmp/contaneta-drill && cd /tmp/contaneta-drill

# 2. Decompress latest backup
cp /var/backups/contaneta/invoicing_*.db.gz .
gunzip $(ls -t invoicing_*.db.gz | head -1)

# 3. Verify integrity
sqlite3 invoicing_*.db "PRAGMA integrity_check;"

# 4. Verify data
sqlite3 invoicing_*.db "SELECT COUNT(*) FROM users; SELECT COUNT(*) FROM invoices; SELECT COUNT(*) FROM issuers;"

# 5. Cleanup
rm -rf /tmp/contaneta-drill
```
