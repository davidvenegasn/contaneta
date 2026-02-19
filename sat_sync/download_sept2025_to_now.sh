#!/usr/bin/env bash
#
# Descarga toda la info de facturas (metadata + XML) desde septiembre 2025 hasta ahora.
# Incluye emitidas y recibidas para todos los clientes con sat_credentials.
#
# Uso: ./sat_sync/download_sept2025_to_now.sh
#
# Pasos:
#   1) Metadata: sync desde ~1 sept 2025 (backfill ~180 días)
#   2) Solicitudes XML: un mes por mes (2025-09 … 2026-02)
#   3) Verify: descarga paquetes del SAT (en loop con pausas)
#   4) Parse: extrae datos de los XML

set -e
cd "$(dirname "$0")/.."
PROJECT_DIR="$(pwd)"
PHP="$(command -v php)"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

# Meses a solicitar: desde 2025-09 hasta el mes actual (inclusive)
# Genera lista: 2025-09 2025-10 ... YYYY-MM_actual
MONTHS=""
START_Y=2025
START_M=9
NOW_YM=$(date +%Y-%m)
y=$START_Y
m=$START_M
while true; do
  ym=$(printf "%04d-%02d" "$y" "$m")
  MONTHS="$MONTHS $ym"
  [ "$ym" = "$NOW_YM" ] && break
  m=$((m + 1))
  [ $m -gt 12 ] && { m=1; y=$((y + 1)); }
done
MONTHS=$(echo "$MONTHS")

log "=== Descarga facturas desde septiembre 2025 hasta ahora ($NOW_YM) ==="
log "Meses: $MONTHS"

ISSUERS=$(sqlite3 -noheader "$PROJECT_DIR/invoicing.db" \
  "SELECT issuer_id FROM sat_credentials GROUP BY issuer_id" 2>/dev/null || true)
if [ -z "$ISSUERS" ]; then
  log "No hay issuers con sat_credentials."
  exit 1
fi

# 1) Metadata: lista desde ~1 sept 2025 (backfill 180 días, ventanas de 1 semana)
for IID in $ISSUERS; do
  log "Metadata issuer=$IID (reset + backfill 180 días)"
  $PHP sat_sync/sync.php "$IID" issued   --backfill=180 --window=168 --max-windows=20 --reset 2>/dev/null || true
  $PHP sat_sync/sync.php "$IID" received --backfill=180 --window=168 --max-windows=20 --reset 2>/dev/null || true
done

# 2) Crear solicitudes XML por mes (sept 2025 … feb 2026)
for IID in $ISSUERS; do
  log "Solicitudes XML issuer=$IID ($MONTHS)"
  for YM in $MONTHS; do
    $PHP sat_sync/sync_xml.php "$IID" issued   --month="$YM" 2>/dev/null || true
    $PHP sat_sync/sync_xml.php "$IID" received --month="$YM" 2>/dev/null || true
  done
done

# 3) Resetear "verifying" a "queued" para reintentar
PEND=$(sqlite3 "$PROJECT_DIR/invoicing.db" \
  "UPDATE sat_requests SET status='queued' WHERE status='verifying'; SELECT changes();" 2>/dev/null || echo "0")
log "Reseteados a queued: $PEND"

# 4) Loop verify: el SAT tarda en preparar paquetes
MAX_ITER=80
SLEEP=90
for i in $(seq 1 $MAX_ITER); do
  QUEDAN=$(sqlite3 -noheader "$PROJECT_DIR/invoicing.db" \
    "SELECT COUNT(*) FROM sat_requests WHERE status IN ('queued','verifying')" 2>/dev/null || echo "1")

  if [ "$QUEDAN" = "0" ]; then
    log "No hay requests pendientes. Listo."
    break
  fi

  log "Iteración $i/$MAX_ITER - Pendientes: $QUEDAN"
  $PHP sat_sync/verify_requests.php --limit=30 2>/dev/null || true

  if [ "$i" -lt "$MAX_ITER" ]; then
    log "Esperando ${SLEEP}s (el SAT tarda en preparar paquetes)..."
    sleep $SLEEP
  fi
done

# 5) Parsear XML (subtotal, IVA, emisor, receptor, etc.)
log "Parseando XML..."
$PHP sat_sync/parse_xml.php --limit=1000 2>/dev/null || true

# 6) Cancelaciones (opcional, últimos 30 días)
for IID in $ISSUERS; do
  $PHP sat_sync/check_cancellations.php "$IID" --days=30 2>/dev/null || true
done

log "=== Fin descarga sept 2025 → ahora ==="
