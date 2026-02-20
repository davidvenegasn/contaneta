#!/usr/bin/env bash
# Wrapper único para ejecutar el sync SAT por issuer(s).
# Uso:
#   ./scripts/run_sat_sync.sh                    # todos los issuers activos (issued + received)
#   ./scripts/run_sat_sync.sh 1                  # solo issuer_id=1 (issued + received)
#   ./scripts/run_sat_sync.sh 1 issued           # solo issuer 1, dirección issued
#   APP_DB_PATH=/ruta/invoicing.db ./scripts/run_sat_sync.sh
#
# Requiere: php en PATH, sat_sync/sync.php y su composer deps. DB con tabla issuers.
# Para cron (ej. cada 6 horas): 0 */6 * * * cd /ruta/proyecto && ./scripts/run_sat_sync.sh >> /var/log/sat_sync.log 2>&1

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
DB_PATH="${APP_DB_PATH:-$PROJECT_ROOT/invoicing.db}"
SYNC_PHP="$PROJECT_ROOT/sat_sync/sync.php"

if [ ! -f "$SYNC_PHP" ]; then
  echo "No encontrado: $SYNC_PHP"
  exit 1
fi
if [ ! -f "$DB_PATH" ]; then
  echo "No encontrado DB: $DB_PATH"
  exit 1
fi

cd "$PROJECT_ROOT"
export APP_DB_PATH="$DB_PATH"

run_one() {
  local id="$1"
  local dir="${2:-}"
  if [ -z "$dir" ]; then
    php "$SYNC_PHP" "$id" issued || true
    php "$SYNC_PHP" "$id" received || true
  else
    php "$SYNC_PHP" "$id" "$dir" || true
  fi
}

if [ -n "${1:-}" ]; then
  issuer_id="$1"
  direction="${2:-}"
  if ! [[ "$issuer_id" =~ ^[0-9]+$ ]]; then
    echo "Uso: $0 [issuer_id] [issued|received]"
    exit 1
  fi
  run_one "$issuer_id" "$direction"
else
  ids=$(sqlite3 "$DB_PATH" "SELECT id FROM issuers WHERE active = 1 ORDER BY id" 2>/dev/null || true)
  if [ -z "$ids" ]; then
    echo "No hay issuers activos en la DB."
    exit 0
  fi
  for id in $ids; do
    run_one "$id" ""
  done
fi
