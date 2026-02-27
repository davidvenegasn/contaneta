#!/usr/bin/env bash
#
# Comprueba si la cuenta de un email tiene FIEL/credenciales SAT configuradas
# y si se usarían en la sincronización (cron_sat_sync.sh).
#
# Uso: ./scripts/check_sat_credentials_for_email.sh [email]
#      ./scripts/check_sat_credentials_for_email.sh villadavidetn@gmail.com

set -e
cd "$(dirname "$0")/.."
DB="${PWD}/invoicing.db"
EMAIL="${1:-villadavidetn@gmail.com}"

if [ ! -f "$DB" ]; then
  echo "No existe: $DB"
  exit 1
fi

echo "=== Cuenta: $EMAIL ==="
echo ""

# Issuer(s) vinculados al email vía memberships
ISSUER_ROW=$(sqlite3 -header -line "$DB" \
  "SELECT m.issuer_id, i.rfc, i.razon_social
   FROM memberships m
   JOIN users u ON u.id = m.user_id
   LEFT JOIN issuers i ON i.id = m.issuer_id
   WHERE LOWER(TRIM(u.email)) = LOWER(TRIM('${EMAIL}'))
   LIMIT 1" 2>/dev/null || true)

if [ -z "$ISSUER_ROW" ]; then
  echo "No se encontró ningún issuer para este email."
  echo "Verifica que el usuario exista en 'users' y tenga membresía en 'memberships'."
  exit 1
fi

echo "$ISSUER_ROW"
echo ""

# Extraer issuer_id para la siguiente consulta
ISSUER_ID=$(sqlite3 -noheader "$DB" \
  "SELECT m.issuer_id FROM memberships m
   JOIN users u ON u.id = m.user_id
   WHERE LOWER(TRIM(u.email)) = LOWER(TRIM('${EMAIL}'))
   LIMIT 1" 2>/dev/null)

# ¿Tiene sat_credentials (FIEL)?
CRED=$(sqlite3 -header -line "$DB" \
  "SELECT issuer_id, fiel_cer_path, fiel_key_path,
          length(fiel_key_password) as password_length,
          validation_ok, validation_message, validation_at
   FROM sat_credentials
   WHERE issuer_id = $ISSUER_ID
   LIMIT 1" 2>/dev/null || true)

if [ -z "$CRED" ]; then
  echo "Estado: NO tiene FIEL configurada para este issuer."
  echo "El cron_sat_sync.sh NO descargará facturas para esta cuenta hasta que"
  echo "configures la FIEL en el portal (Conectar SAT) con .cer, .key y contraseña."
  exit 1
fi

echo "Credenciales SAT (FIEL) para issuer_id=$ISSUER_ID:"
echo "$CRED"
echo ""

if echo "$CRED" | grep -q "validation_ok = 1"; then
  echo "Conclusión: SÍ. La cuenta tiene FIEL validada. Al ejecutar cron_sat_sync.sh"
  echo "se usará el RFC del certificado (.cer) y esta FIEL para descargar emitidas y recibidas."
else
  echo "Conclusión: Tiene FIEL guardada pero validation_ok != 1. Revalida en el portal"
  echo "(Conectar SAT → Validar de nuevo). Si la contraseña es correcta, después de validar"
  echo "el cron sí usará esta FIEL para la descarga."
fi
