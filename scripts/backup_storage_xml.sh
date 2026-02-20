#!/usr/bin/env bash
# Backup del directorio storage (XMLs descargados). Copia a backup/storage_YYYYMMDD_HHMMSS.
# No borra nada. Uso: ./scripts/backup_storage_xml.sh

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
STORAGE_DIR="${STORAGE_DIR:-$PROJECT_ROOT/storage}"
BACKUP_DIR="${BACKUP_DIR:-$PROJECT_ROOT/backup}"
STAMP="$(date +%Y%m%d_%H%M%S)"

if [ ! -d "$STORAGE_DIR" ]; then
  echo "No existe directorio storage en: $STORAGE_DIR"
  exit 1
fi
mkdir -p "$BACKUP_DIR"
cp -a "$STORAGE_DIR" "$BACKUP_DIR/storage_${STAMP}"
echo "Backup: $BACKUP_DIR/storage_${STAMP}"
