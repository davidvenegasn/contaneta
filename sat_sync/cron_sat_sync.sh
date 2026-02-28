#!/usr/bin/env bash
#
# Cron SAT Sync - procesa todos los clientes (issuers con sat_credentials)
#
# Mejora la descarga:
#   1. Metadata (lista rápida con total, fecha, estado)
#   2. Solicitudes XML
#   3. Descarga de paquetes
#   4. Parseo (subtotal, IVA, etc.)
#   4.5) Backfill clientes: guardar receptores de facturas emitidas en tabla clients
#   5. Verificación de cancelaciones
#
# Crontab recomendado (cada 15 min):
#   */15 * * * * /ruta/al/proyecto/sat_sync/cron_sat_sync.sh >> /tmp/sat_sync.log 2>&1

set -e
cd "$(dirname "$0")/.."
PROJECT_DIR="$(pwd)"
PHP="$(command -v php)"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

# Ejecutar comando con timeout (mata si tarda más de 2 min) - evita que el cron se cuelgue
run_timeout() {
  local secs="${1:-120}"
  shift
  "$@" &
  local pid=$!
  ( sleep "$secs"; kill "$pid" 2>/dev/null ) &
  local killer=$!
  wait "$pid" 2>/dev/null
  local ret=$?
  kill "$killer" 2>/dev/null
  return $ret
}

log "=== Inicio cron SAT sync ==="

ISSUERS=$(sqlite3 -noheader "$PROJECT_DIR/invoicing.db" \
  "SELECT issuer_id FROM sat_credentials GROUP BY issuer_id" 2>/dev/null || true)

if [ -z "$ISSUERS" ]; then
  log "No hay issuers con sat_credentials."
  exit 0
fi

# 1) METADATA: lista rápida (total, fecha, estado) - el SAT prepara metadata más rápido que XML
for IID in $ISSUERS; do
  log "Sync metadata issuer=$IID"
  run_timeout 140 python3 scripts/run_php_with_fiel.py sat_sync/sync.php "$IID" issued   --backfill=60 --window=168 --max-windows=5 2>/dev/null || true
  run_timeout 140 python3 scripts/run_php_with_fiel.py sat_sync/sync.php "$IID" received --backfill=60 --window=168 --max-windows=5 2>/dev/null || true
done

# 2) XML: crear solicitudes para mes actual y anterior
YM=$(date +%Y-%m)
YM_PREV=$(date -v-1m +%Y-%m 2>/dev/null || date -d "1 month ago" +%Y-%m 2>/dev/null || echo "$YM")

for IID in $ISSUERS; do
  log "Sync XML issuer=$IID"
  run_timeout 140 python3 scripts/run_php_with_fiel.py sat_sync/sync_xml.php "$IID" issued   --month="$YM" 2>/dev/null || true
  run_timeout 140 python3 scripts/run_php_with_fiel.py sat_sync/sync_xml.php "$IID" issued   --month="$YM_PREV" 2>/dev/null || true
  run_timeout 140 python3 scripts/run_php_with_fiel.py sat_sync/sync_xml.php "$IID" received --month="$YM" 2>/dev/null || true
  run_timeout 140 python3 scripts/run_php_with_fiel.py sat_sync/sync_xml.php "$IID" received --month="$YM_PREV" 2>/dev/null || true
done

# 3) VERIFY: descargar paquetes XML cuando el SAT los tenga listos
log "Verify + download XML..."
run_timeout 180 $PHP sat_sync/verify_requests.php --limit=20 2>/dev/null || true

# 4) PARSE: extraer subtotal, IVA, fecha, emisor/receptor del XML
log "Parse XML..."
$PHP sat_sync/parse_xml.php --limit=300 2>/dev/null || true

# 4.5) BACKFILL CLIENTES: guardar clientes desde receptores de facturas emitidas (tabla clients)
log "Backfill clientes desde facturas emitidas..."
PYTHON="${PYTHON:-python3}"
if command -v "$PYTHON" >/dev/null 2>&1; then
  run_timeout 120 "$PYTHON" scripts/backfill_clients_from_sat.py 2>/dev/null || true
else
  log "Python no encontrado; omitiendo backfill de clientes."
fi

# 5) CANCELACIONES: actualizar estado de facturas canceladas (una vez por corrida)
for IID in $ISSUERS; do
  run_timeout 140 python3 scripts/run_php_with_fiel.py sat_sync/check_cancellations.php "$IID" --days=30 2>/dev/null || true
done

log "=== Fin cron SAT sync ==="
