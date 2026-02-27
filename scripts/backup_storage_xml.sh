#!/usr/bin/env bash
# Backup del directorio storage (XMLs y credenciales FIEL). Copia a backup/storage_YYYYMMDD_HHMMSS
# (o .tar.gz si BACKUP_STORAGE_ZIP=1). Retención configurable.
#
# Uso: ./scripts/backup_storage_xml.sh
#
# Variables de entorno (opcionales):
#   STORAGE_DIR         Carpeta a respaldar (default: proyecto/storage)
#   BACKUP_DIR          Carpeta donde guardar copias (default: proyecto/backup)
#   BACKUP_RETAIN_DAYS  Días de retención; se borran backups más antiguos (default: 30).
#                       Poner 0 para no borrar ninguno.
#   BACKUP_STORAGE_ZIP  1 o yes = guardar comprimido .tar.gz
#
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
STORAGE_DIR="${STORAGE_DIR:-$PROJECT_ROOT/storage}"
BACKUP_DIR="${BACKUP_DIR:-$PROJECT_ROOT/backup}"
RETAIN_DAYS="${BACKUP_RETAIN_DAYS:-30}"
STAMP="$(date +%Y%m%d_%H%M%S)"
ZIP="${BACKUP_STORAGE_ZIP:-0}"

if [ ! -d "$STORAGE_DIR" ]; then
  echo "No existe directorio storage en: $STORAGE_DIR"
  exit 1
fi
mkdir -p "$BACKUP_DIR"
DEST="$BACKUP_DIR/storage_${STAMP}"
if [ "$ZIP" = "1" ] || [ "$ZIP" = "yes" ]; then
  (cd "$PROJECT_ROOT" && tar czf "${DEST}.tar.gz" storage)
  echo "Backup: ${DEST}.tar.gz"
else
  cp -a "$STORAGE_DIR" "$DEST"
  echo "Backup: $DEST"
fi

# Rotación: borrar backups más antiguos que RETAIN_DAYS (si RETAIN_DAYS > 0)
if [ -n "$RETAIN_DAYS" ] && [ "$RETAIN_DAYS" -gt 0 ] 2>/dev/null; then
  find "$BACKUP_DIR" -maxdepth 1 -name "storage_*" -type d -mtime +"$RETAIN_DAYS" -exec rm -rf {} \; 2>/dev/null || true
  find "$BACKUP_DIR" -maxdepth 1 -name "storage_*.tar.gz" -type f -mtime +"$RETAIN_DAYS" -delete 2>/dev/null || true
fi
