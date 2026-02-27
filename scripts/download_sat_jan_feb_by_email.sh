#!/usr/bin/env bash
#
# Descarga facturas (CFDI) del SAT para enero y febrero de un año dado,
# para la cuenta asociada a un email (usuario con membresía a un issuer con FIEL).
#
# Uso:
#   ./scripts/download_sat_jan_feb_by_email.sh [email] [año]
#   ./scripts/download_sat_jan_feb_by_email.sh villadavidetn@gmail.com 2026
#
# Requisitos: PHP en PATH, base de datos con users, memberships, sat_credentials.
# El issuer del usuario debe tener FIEL configurada y validada.

set -e
cd "$(dirname "$0")/.."
PROJECT_DIR="$(pwd)"
DB="${PROJECT_DIR}/invoicing.db"
PHP="$(command -v php)"

EMAIL="${1:-villadavidetn@gmail.com}"
YEAR="${2:-2026}"
MONTH_01="${YEAR}-01"
MONTH_02="${YEAR}-02"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

if [ ! -f "$DB" ]; then
  log "Error: No existe la base de datos $DB"
  exit 1
fi

# Resolver issuer_id desde el email (users + memberships)
ISSUER_ID=$(sqlite3 -noheader "$DB" \
  "SELECT m.issuer_id FROM memberships m
   JOIN users u ON u.id = m.user_id
   WHERE LOWER(TRIM(u.email)) = LOWER(TRIM('${EMAIL}'))
   LIMIT 1" 2>/dev/null || true)

if [ -z "$ISSUER_ID" ]; then
  log "Error: No se encontró ningún issuer para el email: $EMAIL"
  log "Comprueba que el usuario exista en 'users' y tenga una membresía en 'memberships'."
  exit 1
fi

# Comprobar que el issuer tiene FIEL (sat_credentials)
HAS_CRED=$(sqlite3 -noheader "$DB" \
  "SELECT 1 FROM sat_credentials WHERE issuer_id = $ISSUER_ID AND validation_ok = 1 LIMIT 1" 2>/dev/null || true)
if [ -z "$HAS_CRED" ]; then
  log "Aviso: El issuer_id=$ISSUER_ID no tiene FIEL validada (sat_credentials.validation_ok = 1)."
  log "La descarga puede fallar. Configura y valida la FIEL en el portal para este usuario."
fi

log "=== Descarga SAT Ene-Feb $YEAR para $EMAIL (issuer_id=$ISSUER_ID) ==="

# 0) Metadata (backfill que cubra enero y febrero)
log "Paso 1/4: Metadata (issued + received)..."
$PHP sat_sync/sync.php "$ISSUER_ID" issued   --backfill=60 --window=168 --max-windows=10 2>/dev/null || true
$PHP sat_sync/sync.php "$ISSUER_ID" received --backfill=60 --window=168 --max-windows=10 2>/dev/null || true

# 1) Solicitudes XML para enero y febrero
log "Paso 2/4: Solicitudes XML $MONTH_01 y $MONTH_02..."
$PHP sat_sync/sync_xml.php "$ISSUER_ID" issued   --month="$MONTH_01" 2>/dev/null || true
$PHP sat_sync/sync_xml.php "$ISSUER_ID" issued   --month="$MONTH_02" 2>/dev/null || true
$PHP sat_sync/sync_xml.php "$ISSUER_ID" received --month="$MONTH_01" 2>/dev/null || true
$PHP sat_sync/sync_xml.php "$ISSUER_ID" received --month="$MONTH_02" 2>/dev/null || true

# 2) Resetear requests en "verifying" a "queued" para reintentar
sqlite3 "$DB" "UPDATE sat_requests SET status='queued' WHERE issuer_id=$ISSUER_ID AND status='verifying';" 2>/dev/null || true

# 3) Loop verify: descargar paquetes cuando el SAT los tenga listos
log "Paso 3/4: Verificar y descargar paquetes XML (puede tardar varios minutos)..."
MAX_ITER=40
SLEEP=90
for i in $(seq 1 $MAX_ITER); do
  QUEDAN=$(sqlite3 -noheader "$DB" \
    "SELECT COUNT(*) FROM sat_requests WHERE issuer_id = $ISSUER_ID AND status IN ('queued','verifying')" 2>/dev/null || echo "1")
  if [ "$QUEDAN" = "0" ]; then
    log "Sin requests pendientes para este issuer."
    break
  fi
  log "  Iteración $i/$MAX_ITER - Pendientes: $QUEDAN"
  $PHP sat_sync/verify_requests.php --limit=20 2>/dev/null || true
  if [ "$i" -lt "$MAX_ITER" ]; then
    sleep $SLEEP
  fi
done

# 4) Parsear XML descargados (subtotal, IVA, emisor, receptor, etc.)
log "Paso 4/4: Parsear XML..."
$PHP sat_sync/parse_xml.php --issuer="$ISSUER_ID" --limit=500 2>/dev/null || true

# Resumen
COUNT=$(sqlite3 -noheader "$DB" \
  "SELECT COUNT(*) FROM sat_cfdi WHERE issuer_id = $ISSUER_ID AND fecha_emision >= '$MONTH_01-01' AND fecha_emision < '$YEAR-03-01'" 2>/dev/null || echo "0")
log "=== Fin. CFDI en Ene-Feb $YEAR para issuer $ISSUER_ID: $COUNT ==="
