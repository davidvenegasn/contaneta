#!/usr/bin/env bash
# Backup mínimo del directorio storage (lo esencial para recuperación).
#
# Objetivo:
# - Guardar XML descargados (SAT) y credenciales cifradas (storage/credentials/*.enc).
# - Evitar copiar basura temporal o archivos sensibles en claro.
#
# Uso: ./scripts/backup_storage.sh
#
# Variables de entorno (opcionales):
#   STORAGE_DIR         default: proyecto/storage
#   BACKUP_DIR          default: proyecto/backup
#   BACKUP_RETAIN_DAYS  default: 30
#
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
STORAGE_DIR="${STORAGE_DIR:-$PROJECT_ROOT/storage}"
BACKUP_DIR="${BACKUP_DIR:-$PROJECT_ROOT/backup}"
RETAIN_DAYS="${BACKUP_RETAIN_DAYS:-30}"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT_TAR="$BACKUP_DIR/storage_${STAMP}.tar.gz"

if [ ! -d "$STORAGE_DIR" ]; then
  echo "No existe directorio storage en: $STORAGE_DIR (omitido)"
  exit 0
fi

mkdir -p "$BACKUP_DIR"

# Incluir solo subdirectorios relevantes si existen.
INCLUDES=()
for d in "xml" "credentials" "bank" "exports"; do
  if [ -d "$STORAGE_DIR/$d" ]; then
    INCLUDES+=("$d")
  fi
done

if [ ${#INCLUDES[@]} -eq 0 ]; then
  # fallback: incluye storage completo si no hay estructura conocida
  INCLUDES+=(".")
fi

# --- Database backup (SQLite safe copy via .backup command, WAL-safe) ---
DB_PATH="${APP_DB_PATH:-$PROJECT_ROOT/invoicing.db}"
DB_BACKUP="$BACKUP_DIR/invoicing_${STAMP}.db"
if [ -f "$DB_PATH" ]; then
  if command -v sqlite3 &>/dev/null; then
    sqlite3 "$DB_PATH" ".backup '${DB_BACKUP}'" 2>/dev/null || cp "$DB_PATH" "$DB_BACKUP"
  else
    cp "$DB_PATH" "$DB_BACKUP"
  fi
  echo "DB backup: $DB_BACKUP"
else
  echo "WARN: Database not found at $DB_PATH — skipping DB backup"
fi

(
  cd "$STORAGE_DIR"
  tar -czf "$OUT_TAR" \
    --exclude="tmp/*" \
    --exclude="cache/*" \
    --exclude="**/*.cer" \
    --exclude="**/*.key" \
    "${INCLUDES[@]}"
)

echo "Storage backup: $OUT_TAR"

# Rotación: borrar copias más antiguas que RETAIN_DAYS (si RETAIN_DAYS > 0)
if [ -n "$RETAIN_DAYS" ] && [ "$RETAIN_DAYS" -gt 0 ] 2>/dev/null; then
  find "$BACKUP_DIR" -maxdepth 1 \( -name "storage_*.tar.gz" -o -name "invoicing_*.db" \) -type f -mtime +"$RETAIN_DAYS" -delete 2>/dev/null || true
fi
