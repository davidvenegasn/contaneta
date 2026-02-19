#!/usr/bin/env bash
#
# Descarga todos los XML pendientes ahora.
# Reintenta hasta que el SAT termine de preparar los paquetes.
#
# Uso: ./sat_sync/download_all_xml_now.sh

set -e
cd "$(dirname "$0")/.."
PROJECT_DIR="$(pwd)"
PHP="$(command -v php)"

log() { echo "[$(date '+%H:%M:%S')] $*"; }

log "=== Descarga de XML - Inicio ==="

# 0) Metadata primero (lista rápida)
ISSUERS=$(sqlite3 -noheader "$PROJECT_DIR/invoicing.db" "SELECT issuer_id FROM sat_credentials GROUP BY issuer_id" 2>/dev/null || true)
for IID in $ISSUERS; do
  log "Metadata issuer=$IID"
  $PHP sat_sync/sync.php "$IID" issued   --backfill=60 --window=168 --max-windows=10 2>/dev/null || true
  $PHP sat_sync/sync.php "$IID" received --backfill=60 --window=168 --max-windows=10 2>/dev/null || true
done

# 1) Resetear requests "verifying" a "queued" (para reintentar)
PEND=$(sqlite3 "$PROJECT_DIR/invoicing.db" \
  "UPDATE sat_requests SET status='queued' WHERE status='verifying'; SELECT changes();" 2>/dev/null || echo "0")
log "Reseteados a queued: $PEND"

# 2) Loop: verify hasta que no queden pendientes o max 40 intentos (~60 min)
MAX_ITER=40
SLEEP=90

for i in $(seq 1 $MAX_ITER); do
  QUEDAN=$(sqlite3 -noheader "$PROJECT_DIR/invoicing.db" \
    "SELECT COUNT(*) FROM sat_requests WHERE status IN ('queued','verifying')" 2>/dev/null || echo "1")

  if [ "$QUEDAN" = "0" ]; then
    log "No hay requests pendientes. Listo."
    break
  fi

  log "Iteración $i/$MAX_ITER - Pendientes: $QUEDAN"
  $PHP sat_sync/verify_requests.php --limit=20 || true

  if [ "$i" -lt "$MAX_ITER" ]; then
    log "Esperando ${SLEEP}s (el SAT tarda en preparar paquetes)..."
    sleep $SLEEP
  fi
done

# 3) Parsear XML descargados
log "Parseando XML..."
$PHP sat_sync/parse_xml.php --limit=500 || true

log "=== Fin ==="
