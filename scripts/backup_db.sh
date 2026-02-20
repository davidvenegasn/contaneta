#!/usr/bin/env bash
# Backup de la base SQLite (invoicing.db) con rotación.
# Uso: ./scripts/backup_db.sh   o   APP_DB_PATH=/ruta/invoicing.db ./scripts/backup_db.sh
# Rotación: se mantienen los últimos BACKUP_RETAIN_DAYS días (default 30).

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
DB_PATH="${APP_DB_PATH:-$PROJECT_ROOT/invoicing.db}"
BACKUP_DIR="${BACKUP_DIR:-$PROJECT_ROOT/backup}"
RETAIN_DAYS="${BACKUP_RETAIN_DAYS:-30}"
STAMP="$(date +%Y%m%d_%H%M%S)"

if [ ! -f "$DB_PATH" ]; then
  echo "No existe DB en: $DB_PATH"
  exit 1
fi
mkdir -p "$BACKUP_DIR"
cp -a "$DB_PATH" "$BACKUP_DIR/invoicing_${STAMP}.db"
echo "Backup: $BACKUP_DIR/invoicing_${STAMP}.db"

# Rotación: borrar copias de la DB más antiguas que RETAIN_DAYS
find "$BACKUP_DIR" -maxdepth 1 -name "invoicing_*.db" -type f -mtime +"$RETAIN_DAYS" -delete 2>/dev/null || true
