#!/usr/bin/env bash
#
# Descarga XML desde enero 2025 y lo que va de febrero.
# Crea solicitudes para 2026-01 y 2026-02, luego verify + parse.
#
# Uso: ./sat_sync/download_jan_feb.sh

set -e
cd "$(dirname "$0")/.."
PROJECT_DIR="$(pwd)"
PHP="$(command -v php)"

log() { echo "[$(date '+%H:%M:%S')] $*"; }

log "=== Descarga XML Ene-Feb 2025 ==="

ISSUERS=$(sqlite3 -noheader "$PROJECT_DIR/invoicing.db" "SELECT issuer_id FROM sat_credentials GROUP BY issuer_id" 2>/dev/null || true)
if [ -z "$ISSUERS" ]; then
  log "No hay issuers con sat_credentials."
  exit 1
fi

# 0) Metadata desde ~1 enero (backfill 50 días)
for IID in $ISSUERS; do
  log "Metadata issuer=$IID (reset + backfill 50 días)"
  $PHP sat_sync/sync.php "$IID" issued   --backfill=50 --window=168 --max-windows=10 --reset 2>/dev/null || true
  $PHP sat_sync/sync.php "$IID" received --backfill=50 --window=168 --max-windows=10 --reset 2>/dev/null || true
done

# 1) Crear solicitudes XML para enero y febrero
for IID in $ISSUERS; do
  log "Solicitudes XML issuer=$IID (2025-01, 2025-02)"
  $PHP sat_sync/sync_xml.php "$IID" issued   --month=2025-01 2>/dev/null || true
  $PHP sat_sync/sync_xml.php "$IID" issued   --month=2025-02 2>/dev/null || true
  $PHP sat_sync/sync_xml.php "$IID" received --month=2025-01 2>/dev/null || true
  $PHP sat_sync/sync_xml.php "$IID" received --month=2025-02 2>/dev/null || true
done

# 2) Resetear "verifying" a "queued"
PEND=$(sqlite3 "$PROJECT_DIR/invoicing.db" \
  "UPDATE sat_requests SET status='queued' WHERE status='verifying'; SELECT changes();" 2>/dev/null || echo "0")
log "Reseteados a queued: $PEND"

# 3) Loop verify
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

# 4) Parsear XML
log "Parseando XML..."
$PHP sat_sync/parse_xml.php --limit=500 || true

log "=== Fin ==="
