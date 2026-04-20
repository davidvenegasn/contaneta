#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────
# ContaNeta Backup Verify — non-destructive backup drill
#
# Creates a fresh backup, verifies integrity, prints summary.
# Does NOT modify the live database or storage.
#
# Usage: bash scripts/backup_verify.sh
# Exit: 0 = OK, 1 = FAIL
# ──────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
DB_PATH="${APP_DB_PATH:-$PROJECT_ROOT/invoicing.db}"
BACKUP_DIR="${BACKUP_DIR:-$PROJECT_ROOT/backup}"
TEMP_DB=""
CLEANUP_FILES=()

cleanup() {
  for f in "${CLEANUP_FILES[@]}"; do
    rm -f "$f" 2>/dev/null || true
  done
}
trap cleanup EXIT

echo "===== ContaNeta Backup Verify — $(date -u '+%Y-%m-%d %H:%M:%S UTC') ====="
echo ""

# 1. Check source DB exists
if [ ! -f "$DB_PATH" ]; then
  echo "FAIL: Database not found at $DB_PATH"
  exit 1
fi
echo "Source DB: $DB_PATH ($(du -h "$DB_PATH" | cut -f1))"

# 2. Create a WAL-safe backup copy
TEMP_DB="$(mktemp -t backup_verify_XXXXXX.db)"
CLEANUP_FILES+=("$TEMP_DB")

if command -v sqlite3 &>/dev/null; then
  sqlite3 "$DB_PATH" ".backup '$TEMP_DB'" 2>/dev/null
  echo "Backup method: sqlite3 .backup (WAL-safe)"
else
  cp "$DB_PATH" "$TEMP_DB"
  echo "Backup method: file copy (sqlite3 not found)"
fi

# 3. Integrity check
echo ""
echo "--- Integrity Check ---"
if ! command -v sqlite3 &>/dev/null; then
  echo "FAIL: sqlite3 not installed — cannot verify integrity"
  exit 1
fi

integrity=$(sqlite3 "$TEMP_DB" "PRAGMA integrity_check;" 2>&1)
if [ "$integrity" != "ok" ]; then
  echo "FAIL: Integrity check returned: $integrity"
  exit 1
fi
echo "PRAGMA integrity_check: OK"

# 4. Row counts
echo ""
echo "--- Data Summary ---"
users=$(sqlite3 "$TEMP_DB" "SELECT COUNT(*) FROM users;" 2>/dev/null || echo "?")
issuers=$(sqlite3 "$TEMP_DB" "SELECT COUNT(*) FROM issuers;" 2>/dev/null || echo "?")
cfdi=$(sqlite3 "$TEMP_DB" "SELECT COUNT(*) FROM sat_cfdi;" 2>/dev/null || echo "?")
cfdi_xml=$(sqlite3 "$TEMP_DB" "SELECT COUNT(*) FROM sat_cfdi WHERE xml_path IS NOT NULL AND TRIM(COALESCE(xml_path,'')) != '';" 2>/dev/null || echo "?")
invoices=$(sqlite3 "$TEMP_DB" "SELECT COUNT(*) FROM invoices;" 2>/dev/null || echo "?")
jobs=$(sqlite3 "$TEMP_DB" "SELECT COUNT(*) FROM jobs;" 2>/dev/null || echo "?")
migrations=$(sqlite3 "$TEMP_DB" "SELECT COUNT(*) FROM schema_migrations;" 2>/dev/null || echo "?")
last_migration=$(sqlite3 "$TEMP_DB" "SELECT version FROM schema_migrations ORDER BY version DESC LIMIT 1;" 2>/dev/null || echo "?")

echo "  Users:      $users"
echo "  Issuers:    $issuers"
echo "  CFDIs:      $cfdi (con XML: $cfdi_xml)"
echo "  Invoices:   $invoices"
echo "  Jobs:       $jobs"
echo "  Migrations: $migrations (latest: $last_migration)"

# 5. Check existing backups in backup dir
echo ""
echo "--- Backup Directory ---"
if [ -d "$BACKUP_DIR" ]; then
  db_backups=$(find "$BACKUP_DIR" -maxdepth 1 -name "invoicing_*.db*" -type f 2>/dev/null | wc -l | tr -d ' ')
  storage_backups=$(find "$BACKUP_DIR" -maxdepth 1 -name "storage_*.tar.gz" -type f 2>/dev/null | wc -l | tr -d ' ')
  latest=$(ls -t "$BACKUP_DIR"/invoicing_*.db* 2>/dev/null | head -1 || echo "none")
  echo "  DB backups:      $db_backups"
  echo "  Storage backups: $storage_backups"
  echo "  Latest:          $(basename "$latest" 2>/dev/null || echo "none")"
else
  echo "  Backup dir not found: $BACKUP_DIR"
fi

echo ""
echo "===== Backup Verify: OK ====="
exit 0
