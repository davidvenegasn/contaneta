#!/usr/bin/env bash
# Backup de la base SQLite (invoicing.db) con retención configurable.
#
# Uso: ./scripts/backup_db.sh
#
# Variables de entorno (opcionales):
#   APP_DB_PATH      Ruta del archivo .db (default: proyecto/invoicing.db)
#   BACKUP_DIR       Carpeta donde guardar copias (default: proyecto/backup)
#   BACKUP_RETAIN_DAYS  Días de retención; se borran copias más antiguas (default: 30).
#                       Poner 0 para no borrar ninguna copia antigua.
#
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

# Rotación: borrar copias más antiguas que RETAIN_DAYS (si RETAIN_DAYS > 0)
if [ -n "$RETAIN_DAYS" ] && [ "$RETAIN_DAYS" -gt 0 ] 2>/dev/null; then
  find "$BACKUP_DIR" -maxdepth 1 -name "invoicing_*.db" -type f -mtime +"$RETAIN_DAYS" -delete 2>/dev/null || true
fi
