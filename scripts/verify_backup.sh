#!/usr/bin/env bash
# verify_backup.sh — Verify a SQLite backup is valid and restorable.
# Usage: bash scripts/verify_backup.sh <backup.db>
set -euo pipefail

BACKUP="${1:-}"
if [ -z "$BACKUP" ] || [ ! -f "$BACKUP" ]; then
    echo "Usage: bash scripts/verify_backup.sh <backup.db>"
    echo "  Verifies integrity, checks key tables, and reports row counts."
    exit 1
fi

echo "=== Backup Verification: $BACKUP ==="
echo "File size: $(du -h "$BACKUP" | cut -f1)"
echo ""

# 1. Integrity check
echo "--- Integrity Check ---"
RESULT=$(sqlite3 "$BACKUP" "PRAGMA integrity_check;" 2>&1)
if [ "$RESULT" = "ok" ]; then
    echo "  PASS: integrity_check = ok"
else
    echo "  FAIL: $RESULT"
    exit 1
fi

# 2. Schema migrations
echo ""
echo "--- Schema Migrations ---"
MIGRATION_COUNT=$(sqlite3 "$BACKUP" "SELECT COUNT(*) FROM schema_migrations;" 2>/dev/null || echo "0")
LATEST=$(sqlite3 "$BACKUP" "SELECT version FROM schema_migrations ORDER BY version DESC LIMIT 1;" 2>/dev/null || echo "none")
echo "  Migrations applied: $MIGRATION_COUNT"
echo "  Latest version: $LATEST"

# 3. Key table row counts
echo ""
echo "--- Row Counts ---"
TABLES="issuers users memberships sat_cfdi invoices customer_profiles issuer_products bank_movements quotations jobs"
for TABLE in $TABLES; do
    COUNT=$(sqlite3 "$BACKUP" "SELECT COUNT(*) FROM $TABLE;" 2>/dev/null || echo "N/A")
    printf "  %-25s %s\n" "$TABLE" "$COUNT"
done

# 4. Check for required tables
echo ""
echo "--- Required Tables Check ---"
REQUIRED="issuers users memberships schema_migrations"
ALL_OK=true
for TABLE in $REQUIRED; do
    EXISTS=$(sqlite3 "$BACKUP" "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='$TABLE';" 2>/dev/null || echo "0")
    if [ "$EXISTS" = "1" ]; then
        echo "  $TABLE: EXISTS"
    else
        echo "  $TABLE: MISSING"
        ALL_OK=false
    fi
done

echo ""
if [ "$ALL_OK" = true ]; then
    echo "=== VERIFICATION PASSED ==="
else
    echo "=== VERIFICATION FAILED: missing required tables ==="
    exit 1
fi
