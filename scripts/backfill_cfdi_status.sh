#!/usr/bin/env bash
# Rellena status = 'V' (Vigente) en sat_cfdi donde esté NULL o vacío.
# Luego ejecuta check_cancellations para marcar las canceladas.
# Uso: ./scripts/backfill_cfdi_status.sh [días para cancelaciones, default 365]

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BASE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
DB="${APP_DB_PATH:-$BASE_DIR/invoicing.db}"
DAYS="${1:-365}"

if [ ! -f "$DB" ]; then
  echo "No se encontró base de datos: $DB" >&2
  exit 1
fi

echo "=== Backfill estatus CFDI (sin estatus -> Vigente) ==="
UPDATED=$(sqlite3 "$DB" "UPDATE sat_cfdi SET status = 'V' WHERE status IS NULL OR TRIM(COALESCE(status, '')) = ''; SELECT changes();")
echo "Filas actualizadas a status='V': $UPDATED"

echo "=== Verificando cancelaciones (últimos $DAYS días) ==="
PHP="${PHP_BIN:-php}"
for IID in $(sqlite3 -noheader "$DB" "SELECT issuer_id FROM sat_credentials GROUP BY issuer_id" 2>/dev/null || true); do
  [ -z "$IID" ] && continue
  echo "Issuer $IID..."
  "$PHP" "$BASE_DIR/sat_sync/check_cancellations.php" "$IID" --days="$DAYS" 2>/dev/null || true
done
echo "Listo."
