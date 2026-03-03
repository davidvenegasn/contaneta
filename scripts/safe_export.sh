#!/usr/bin/env bash
# safe_export.sh — Create a deployable zip WITHOUT secrets or storage.
# Usage: bash scripts/safe_export.sh [output_name]
set -euo pipefail

PROJ_DIR="$(cd "$(dirname "$0")/.." && pwd)"
OUT_NAME="${1:-contaneta_deploy_$(date +%Y%m%d_%H%M%S).zip}"
OUT_PATH="$PROJ_DIR/$OUT_NAME"
TEMP_DIR=$(mktemp -d)

trap 'rm -rf "$TEMP_DIR"' EXIT

echo "==> Exporting deployable package..."

# Copy only allowed files
rsync -a --exclude-from=- "$PROJ_DIR/" "$TEMP_DIR/app/" <<'EXCLUDES'
.env
.env.*
storage/
backup/
sqlite_aux_backup/
.venv/
venv/
__pycache__/
*.pyc
*.pyo
*.log
*.bak
*.bad
invoicing.db
invoicing.db-*
invoicing.db.*
keys/
_snapshot_*/
.claude/
.git/
.DS_Store
tests/
docs/
node_modules/
*.zip
EXCLUDES

# Build the zip
cd "$TEMP_DIR"
zip -r "$OUT_PATH" app/ -x "*.pyc" "*.pyo" "*__pycache__*" > /dev/null

echo "==> Verifying zip does not contain secrets..."

# Safety checks: fail if dangerous files are inside
VIOLATIONS=""
for pattern in ".env" "storage/credentials" "invoicing.db" ".db" "keys/" ".venv/" "backup/" "backups/"; do
    if zipinfo -1 "$OUT_PATH" 2>/dev/null | grep -q "$pattern"; then
        VIOLATIONS="$VIOLATIONS  FOUND: $pattern\n"
    fi
done

if [ -n "$VIOLATIONS" ]; then
    echo ""
    echo "!!! SECURITY VIOLATION — zip contains forbidden files:"
    printf "$VIOLATIONS"
    echo ""
    echo "Deleting unsafe zip."
    rm -f "$OUT_PATH"
    exit 1
fi

SIZE=$(du -h "$OUT_PATH" | cut -f1)
echo "==> OK: $OUT_PATH ($SIZE)"
echo "==> No secrets detected."
