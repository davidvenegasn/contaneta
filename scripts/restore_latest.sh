#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────
# ContaNeta Restore — restore from the latest (or specified) backup
#
# Usage:
#   bash scripts/restore_latest.sh                    # latest backup
#   bash scripts/restore_latest.sh invoicing_20260301_020000.db.gz  # specific backup
#
# IMPORTANT: Stops the web service before restoring. Run as root or sudo.
# ──────────────────────────────────────────────────────────────
set -euo pipefail

DB_PATH="${APP_DB_PATH:-/var/lib/contaneta/invoicing.db}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/contaneta}"
STORAGE_BASE="${APP_STORAGE_PATH:-/var/lib/contaneta/storage}"
SPECIFIC_BACKUP="${1:-}"

echo "===== ContaNeta Restore — $(date -u '+%Y-%m-%d %H:%M:%S UTC') ====="
echo ""

# 1) Find the backup to restore
if [ -n "$SPECIFIC_BACKUP" ]; then
    DB_BACKUP="$BACKUP_DIR/$SPECIFIC_BACKUP"
    if [ ! -f "$DB_BACKUP" ]; then
        echo "ERROR: Backup file not found: $DB_BACKUP"
        exit 1
    fi
else
    DB_BACKUP=$(ls -t "$BACKUP_DIR"/invoicing_*.db.gz 2>/dev/null | head -1 || true)
    if [ -z "$DB_BACKUP" ]; then
        echo "ERROR: No backup files found in $BACKUP_DIR"
        exit 1
    fi
fi

echo "Backup file: $DB_BACKUP"
echo "Target DB:   $DB_PATH"
echo ""

# Safety confirmation
read -p "This will REPLACE the current database. Continue? (yes/no): " confirm
if [ "$confirm" != "yes" ]; then
    echo "Aborted."
    exit 0
fi

# 2) Stop services
echo ""
echo "--- Stopping services ---"
for svc in contaneta-web contaneta-worker contaneta-sat-scheduler; do
    if systemctl is-active "$svc" &>/dev/null 2>&1; then
        echo "  Stopping $svc..."
        systemctl stop "$svc" 2>/dev/null || true
    fi
done
sleep 2

# 3) Backup current DB (just in case)
if [ -f "$DB_PATH" ]; then
    pre_restore="$BACKUP_DIR/pre_restore_$(date +%Y%m%d_%H%M%S).db"
    echo "  Saving current DB to $pre_restore"
    cp "$DB_PATH" "$pre_restore"
fi

# 4) Restore database
echo ""
echo "--- Restoring database ---"
TEMP_DB=$(mktemp)
gunzip -c "$DB_BACKUP" > "$TEMP_DB"

# Verify integrity before replacing
echo "  Verifying backup integrity..."
integrity=$(sqlite3 "$TEMP_DB" "PRAGMA quick_check;" 2>/dev/null || echo "FAILED")
if [ "$integrity" != "ok" ]; then
    echo "ERROR: Backup integrity check FAILED. Aborting restore."
    rm -f "$TEMP_DB"
    exit 1
fi
echo "  Integrity: OK"

# Replace
cp "$TEMP_DB" "$DB_PATH"
rm -f "$TEMP_DB"
rm -f "${DB_PATH}-wal" "${DB_PATH}-shm"  # Remove stale WAL/SHM

# Fix permissions
chown contaneta:contaneta "$DB_PATH" 2>/dev/null || true
chmod 600 "$DB_PATH"

echo "  Database restored from: $(basename "$DB_BACKUP")"

# 5) Restore storage (optional)
STORAGE_DATE=$(basename "$DB_BACKUP" | sed 's/invoicing_\(.*\)\.db\.gz/\1/')
STORAGE_BACKUP="$BACKUP_DIR/storage_${STORAGE_DATE}.tar.gz"
if [ -f "$STORAGE_BACKUP" ]; then
    echo ""
    read -p "Storage backup found ($STORAGE_BACKUP). Restore? (yes/no): " restore_storage
    if [ "$restore_storage" = "yes" ]; then
        echo "  Restoring storage..."
        tar xzf "$STORAGE_BACKUP" -C "$(dirname "$STORAGE_BASE")" 2>/dev/null || true
        echo "  Storage restored."
    fi
fi

# 6) Restart services
echo ""
echo "--- Restarting services ---"
for svc in contaneta-web contaneta-worker; do
    echo "  Starting $svc..."
    systemctl start "$svc" 2>/dev/null || true
done

echo ""
echo "===== Restore complete ====="
echo ""
echo "Post-restore checklist:"
echo "  1. Check /health endpoint"
echo "  2. Check /admin/dashboard for data"
echo "  3. Verify recent invoices/clients are present"
echo "  4. Check logs: journalctl -u contaneta-web -n 50"
