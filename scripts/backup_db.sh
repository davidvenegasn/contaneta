#!/usr/bin/env bash
# Backup de la base SQLite (invoicing.db). No borra nada; copia a backup/ con timestamp.
# Uso: ./scripts/backup_db.sh   o   APP_DB_PATH=/ruta/invoicing.db ./scripts/backup_db.sh

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
DB_PATH="${APP_DB_PATH:-$PROJECT_ROOT/invoicing.db}"
BACKUP_DIR="${BACKUP_DIR:-$PROJECT_ROOT/backup}"
STAMP="$(date +%Y%m%d_%H%M%S)"

if [ ! -f "$DB_PATH" ]; then
  echo "No existe DB en: $DB_PATH"
  exit 1
fi
mkdir -p "$BACKUP_DIR"
cp -a "$DB_PATH" "$BACKUP_DIR/invoicing_${STAMP}.db"
echo "Backup: $BACKUP_DIR/invoicing_${STAMP}.db"
