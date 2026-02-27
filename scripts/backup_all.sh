#!/usr/bin/env bash
# Backup completo: base de datos + storage (XMLs y credenciales). Retención aplicada en cada script.
#
# Uso: ./scripts/backup_all.sh
#
# Variables (opcionales): APP_DB_PATH, BACKUP_DIR, BACKUP_RETAIN_DAYS, STORAGE_DIR, BACKUP_STORAGE_ZIP
# Ver scripts/backup_db.sh y scripts/backup_storage_xml.sh para detalles.
#
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
cd "$SCRIPT_DIR/.."
echo "=== Backup DB ==="
./scripts/backup_db.sh
echo "=== Backup storage ==="
./scripts/backup_storage_xml.sh
echo "=== Backup completo terminado ==="
