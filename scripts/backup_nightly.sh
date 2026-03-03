#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────
# ContaNeta Nightly Backup
# Backs up SQLite DB + storage/xml_files with 7-day rotation.
# Optional S3-compatible upload via rclone.
#
# Usage:
#   ./scripts/backup_nightly.sh
#   BACKUP_DIR=/custom/path ./scripts/backup_nightly.sh
# ──────────────────────────────────────────────────────────────
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/contaneta}"
DB_PATH="${APP_DB_PATH:-$APP_DIR/invoicing.db}"
BACKUP_DIR="${BACKUP_DIR:-$APP_DIR/backups}"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-7}"
DATE=$(date +%Y%m%d_%H%M%S)
HOSTNAME=$(hostname -s)

mkdir -p "$BACKUP_DIR"

echo "$(date): Starting nightly backup..."

# 1) SQLite backup (online, safe with WAL)
DB_BACKUP="$BACKUP_DIR/invoicing_${DATE}.db"
if [ -f "$DB_PATH" ]; then
    sqlite3 "$DB_PATH" ".backup '$DB_BACKUP'"
    gzip "$DB_BACKUP"
    echo "  DB backup: ${DB_BACKUP}.gz ($(du -h "${DB_BACKUP}.gz" | cut -f1))"
else
    echo "  WARNING: DB not found at $DB_PATH"
fi

# 2) Storage backup (XML files, credentials excluded)
STORAGE_DIR="$APP_DIR/storage"
if [ -d "$STORAGE_DIR" ]; then
    STORAGE_BACKUP="$BACKUP_DIR/storage_${DATE}.tar.gz"
    tar czf "$STORAGE_BACKUP" \
        -C "$APP_DIR" \
        --exclude="storage/credentials" \
        --exclude="storage/temp" \
        storage/ 2>/dev/null || true
    echo "  Storage backup: $STORAGE_BACKUP ($(du -h "$STORAGE_BACKUP" | cut -f1))"
fi

# 3) Rotate old backups (keep last N days)
echo "  Rotating backups older than $RETENTION_DAYS days..."
find "$BACKUP_DIR" -name "invoicing_*.db.gz" -mtime +"$RETENTION_DAYS" -delete 2>/dev/null || true
find "$BACKUP_DIR" -name "storage_*.tar.gz" -mtime +"$RETENTION_DAYS" -delete 2>/dev/null || true

# 4) Optional: upload to S3-compatible storage via rclone
#    Configure with: rclone config (create a remote named "contaneta-backup")
#    Set BACKUP_RCLONE_REMOTE=contaneta-backup:bucket-name/path
if [ -n "${BACKUP_RCLONE_REMOTE:-}" ]; then
    echo "  Uploading to remote: $BACKUP_RCLONE_REMOTE"
    rclone copy "$BACKUP_DIR/" "$BACKUP_RCLONE_REMOTE/" \
        --include "invoicing_${DATE}*" \
        --include "storage_${DATE}*" \
        --transfers 2 \
        --retries 3 2>&1 || echo "  WARNING: rclone upload failed"
fi

echo "$(date): Backup complete."
