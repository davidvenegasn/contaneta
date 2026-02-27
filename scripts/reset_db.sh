#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> Reset DB local (solo desarrollo)"
echo "Esto eliminará archivos locales ignorados por git:"
echo "  - invoicing.db, invoicing.db-* y variantes"
echo ""

if [ "${FORCE_RESET_DB:-0}" != "1" ]; then
  read -r -p "¿Continuar? (escribe RESET para confirmar): " CONFIRM
  if [ "$CONFIRM" != "RESET" ]; then
    echo "Cancelado."
    exit 1
  fi
fi

rm -f \
  invoicing.db \
  invoicing.db-* \
  invoicing.db.* \
  invoicing_new_empty.db \
  fixed.db || true

echo "OK. DB local eliminada."
echo "Vuelve a arrancar el server para que se regenere/migre según corresponda."

