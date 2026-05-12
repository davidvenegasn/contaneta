# Backup Production Runbook — ContaNeta

**Date:** 2026-05-12

## Strategy: 3-2-1

| Rule | Implementation |
|------|---------------|
| **3 copies** | Live DB + local compressed backup + S3 remote |
| **2 media types** | Local SSD + AWS S3 (STANDARD_IA) |
| **1 offsite** | S3 bucket in a different region than the server |

## RPO / RTO Targets (200 users)

| Metric | Target | How |
|--------|--------|-----|
| **RPO** (Recovery Point Objective) | ≤ 24 hours | Daily backup at 03:00 UTC |
| **RTO** (Recovery Time Objective) | ≤ 30 minutes | Download from S3 + restore SQLite |
| **DB size estimate** | ~50–200 MB | 200 issuers × ~1000 invoices each |
| **Compressed size** | ~10–40 MB | gzip -9 on SQLite |

## Components

### 1. Backup script: `scripts/backup_to_s3.sh.example`

Rename to `backup_to_s3.sh` and make executable. Steps:
1. Atomic SQLite `.backup` (safe with WAL mode)
2. `PRAGMA integrity_check` on the copy
3. `gzip -9` compression
4. Upload to S3 with `STANDARD_IA` storage class
5. Verify upload exists
6. Rotate backups older than 30 days

### 2. Systemd timer: `deploy/backup.timer` + `deploy/backup.service`

```bash
# Install (do NOT enable until script is configured)
sudo cp deploy/backup.service /etc/systemd/system/contaneta-backup.service
sudo cp deploy/backup.timer /etc/systemd/system/contaneta-backup.timer
sudo systemctl daemon-reload

# Enable when ready
sudo systemctl enable --now contaneta-backup.timer

# Check status
systemctl list-timers | grep contaneta
journalctl -u contaneta-backup.service --since today
```

### 3. S3 bucket setup

```bash
# Create bucket with versioning
aws s3 mb s3://contaneta-backups-prod --region us-east-1
aws s3api put-bucket-versioning \
  --bucket contaneta-backups-prod \
  --versioning-configuration Status=Enabled

# Lifecycle rule: move to Glacier after 90 days, delete after 365
aws s3api put-bucket-lifecycle-configuration \
  --bucket contaneta-backups-prod \
  --lifecycle-configuration '{
    "Rules": [{
      "ID": "backup-lifecycle",
      "Status": "Enabled",
      "Filter": {"Prefix": "daily/"},
      "Transitions": [{"Days": 90, "StorageClass": "GLACIER"}],
      "Expiration": {"Days": 365}
    }]
  }'
```

### 4. IAM policy (least privilege)

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": ["s3:PutObject", "s3:GetObject", "s3:ListBucket", "s3:DeleteObject"],
    "Resource": [
      "arn:aws:s3:::contaneta-backups-prod",
      "arn:aws:s3:::contaneta-backups-prod/*"
    ]
  }]
}
```

## Monthly Restore Test Procedure

Run this on the **first Monday of each month**:

```bash
# 1. Download latest backup
LATEST=$(aws s3 ls s3://contaneta-backups-prod/daily/ --recursive | sort | tail -1 | awk '{print $4}')
aws s3 cp "s3://contaneta-backups-prod/${LATEST}" /tmp/restore_test.db.gz

# 2. Decompress
gunzip /tmp/restore_test.db.gz

# 3. Integrity check
sqlite3 /tmp/restore_test.db "PRAGMA integrity_check;"
# Expected: "ok"

# 4. Verify data
sqlite3 /tmp/restore_test.db "SELECT COUNT(*) FROM issuers;"
sqlite3 /tmp/restore_test.db "SELECT COUNT(*) FROM sat_cfdi;"
sqlite3 /tmp/restore_test.db "SELECT MAX(created_at) FROM sat_cfdi;"

# 5. Compare row counts with production
# Production counts should match backup (±1 day of new data)

# 6. Cleanup
rm /tmp/restore_test.db

# 7. Log result
echo "$(date): Restore test PASSED — $(sqlite3 /tmp/restore_test.db 'SELECT COUNT(*) FROM issuers;') issuers" >> /var/log/contaneta/restore_tests.log
```

## Disaster Recovery

### Full restore from S3

```bash
# 1. Stop the application
sudo systemctl stop contaneta-web contaneta-worker

# 2. Download and restore
aws s3 cp "s3://contaneta-backups-prod/daily/YYYYMMDD_HHMMSS/invoicing_YYYYMMDD_HHMMSS.db.gz" /tmp/
gunzip /tmp/invoicing_*.db.gz
sqlite3 /tmp/invoicing_*.db "PRAGMA integrity_check;"

# 3. Replace database
mv /opt/contaneta/data/invoicing.db /opt/contaneta/data/invoicing.db.broken
cp /tmp/invoicing_*.db /opt/contaneta/data/invoicing.db
chown contaneta:contaneta /opt/contaneta/data/invoicing.db

# 4. Restart
sudo systemctl start contaneta-web contaneta-worker

# 5. Verify
curl -s http://localhost:8000/health | python3 -m json.tool
```

## Monitoring

- **Alert if no backup in 36 hours**: Check S3 for files newer than yesterday
- **Alert on integrity failure**: Script exits non-zero, systemd logs failure
- **S3 bucket metrics**: Enable CloudWatch request metrics on the bucket

```bash
# Quick check: latest backup age
LATEST_DATE=$(aws s3 ls s3://contaneta-backups-prod/daily/ | sort | tail -1 | awk '{print $2}' | tr -d '/')
echo "Latest backup prefix: $LATEST_DATE"
```
