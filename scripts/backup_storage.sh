#!/usr/bin/env bash
# Backup del directorio storage (XMLs y datos descargados) con rotación.
# Uso: ./scripts/backup_storage.sh
# Rotación: se mantienen los últimos BACKUP_RETAIN_DAYS días (default 30).
# Si no existe storage/, sale sin error (exit 0).

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
STORAGE_DIR="${STORAGE_DIR:-$PROJECT_ROOT/storage}"
BACKUP_DIR="${BACKUP_DIR:-$PROJECT_ROOT/backup}"
RETAIN_DAYS="${BACKUP_RETAIN_DAYS:-30}"
STAMP="$(date +%Y%m%d_%H%M%S)"

if [ ! -d "$STORAGE_DIR" ]; then
  echo "No existe directorio storage en: $STORAGE_DIR (omitido)"
  exit 0
fi
mkdir -p "$BACKUP_DIR"
cp -a "$STORAGE_DIR" "$BACKUP_DIR/storage_${STAMP}"
echo "Backup: $BACKUP_DIR/storage_${STAMP}"

# Rotación: borrar copias de storage más antiguas que RETAIN_DAYS
find "$BACKUP_DIR" -maxdepth 1 -name "storage_*" -type d -mtime +"$RETAIN_DAYS" -exec rm -rf {} + 2>/dev/null || true
