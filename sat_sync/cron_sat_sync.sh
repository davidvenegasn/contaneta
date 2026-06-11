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

# Opcional: --issuer-id=N para procesar sólo ese issuer (usado en onboarding,
# dispara la descarga inmediatamente al subir FIEL en vez de esperar al cron).
# Sin argumento: procesa todos los issuers con sat_credentials (cron normal).
TARGET_ISSUER=""
for arg in "$@"; do
  case "$arg" in
    --issuer-id=*) TARGET_ISSUER="${arg#--issuer-id=}" ;;
  esac
done

if [ -n "$TARGET_ISSUER" ]; then
  ISSUERS="$TARGET_ISSUER"
  log "Modo single-issuer: $TARGET_ISSUER"
else
  ISSUERS=$(sqlite3 -noheader "$PROJECT_DIR/invoicing.db" \
    "SELECT issuer_id FROM sat_credentials GROUP BY issuer_id" 2>/dev/null || true)
fi

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

# 3) VERIFY: descargar paquetes XML cuando el SAT los tenga listos.
# IMPORTANTE: verify_requests.php necesita acceder a los archivos .cer/.key del
# FIEL. Como están encriptados en disco, hay que pasarlos vía env vars que el
# wrapper de Python (decrypted_fiel_env) genera. Si llamamos al PHP
# directamente (sin wrapper), explota con "Cannot parse X509 certificate".
# Por eso loopeamos por issuer y desencriptamos por cada uno.
log "Verify + download XML (per issuer)..."
for IID in $ISSUERS; do
  run_timeout 180 python3 scripts/run_php_with_fiel.py sat_sync/verify_requests.php "$IID" --issuer="$IID" --limit=10 2>/dev/null || true
done

# 4) PARSE: extraer subtotal, IVA, fecha, emisor/receptor del XML.
# IMPORTANTE: si solo corremos --limit=300, los usuarios con cargas iniciales
# grandes (>300 XMLs descargados en una pasada) quedan con CFDIs en estado
# 'downloaded' pero sin fecha_emision/total — y el portal NO los muestra
# porque filtra por mes (que requiere fecha_emision != NULL). Loopeamos
# en batches hasta agotar la cola (con tope de seguridad de 10 rondas para
# evitar loops infinitos por XMLs corruptos).
log "Parse XML (loop hasta agotar)..."
for round in 1 2 3 4 5 6 7 8 9 10; do
  output=$($PHP sat_sync/parse_xml.php --limit=500 2>/dev/null || true)
  echo "$output" | tail -1
  # Si parseó menos de 500 → ya no hay más; salimos
  if echo "$output" | grep -qE "Parseados: [0-4][0-9]{0,2} "; then
    break
  fi
done

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
