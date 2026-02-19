#!/usr/bin/env bash
#
# Actualiza la búsqueda de facturas recientes (esta semana).
# No se va atrás en el tiempo: solo metadata de los últimos 7 días,
# solicitudes XML del mes actual, verify y parse.
#
# Uso: ./sat_sync/sync_recent_week.sh
#
# Útil para que "Actividad reciente" y listados del mes muestren lo nuevo
# sin esperar al cron completo.

set -e
cd "$(dirname "$0")/.."
PROJECT_DIR="$(pwd)"
PHP="$(command -v php)"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

log "=== Sync facturas recientes (esta semana) ==="

ISSUERS=$(sqlite3 -noheader "$PROJECT_DIR/invoicing.db" \
  "SELECT issuer_id FROM sat_credentials GROUP BY issuer_id" 2>/dev/null || true)

if [ -z "$ISSUERS" ]; then
  log "No hay issuers con sat_credentials."
  exit 0
fi

# 1) Metadata: solo últimos 7 días, una ventana (no se va atrás)
for IID in $ISSUERS; do
  log "Metadata reciente issuer=$IID (últimos 7 días)"
  $PHP sat_sync/sync.php "$IID" issued   --backfill=7 --window=168 --max-windows=1 2>/dev/null || true
  $PHP sat_sync/sync.php "$IID" received --backfill=7 --window=168 --max-windows=1 2>/dev/null || true
done

# 2) XML: mes actual (incluye esta semana)
YM=$(date +%Y-%m)
for IID in $ISSUERS; do
  log "Solicitudes XML mes actual issuer=$IID"
  $PHP sat_sync/sync_xml.php "$IID" issued   --month="$YM" 2>/dev/null || true
  $PHP sat_sync/sync_xml.php "$IID" received --month="$YM" 2>/dev/null || true
done

# 3) Descargar paquetes XML que ya estén listos
log "Verificar y descargar XML..."
$PHP sat_sync/verify_requests.php --limit=20 2>/dev/null || true

# 4) Parsear XML descargados
log "Parsear XML..."
$PHP sat_sync/parse_xml.php --limit=200 2>/dev/null || true

log "=== Fin sync reciente ==="
