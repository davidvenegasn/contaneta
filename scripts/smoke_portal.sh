#!/usr/bin/env bash
#
# Smoke test del portal: endpoints clave y comprobación de que las páginas
# HTML no están vacías (evitar pantallas blancas).
#
# Uso:
#   ./scripts/smoke_portal.sh
#   BASE_URL=http://127.0.0.1:9000 ./scripts/smoke_portal.sh
#   START_SERVER=1 ./scripts/smoke_portal.sh
#
set -e
cd "$(dirname "$0")/.."
BASE_URL="${BASE_URL:-http://127.0.0.1:8000}"
BASE_URL="${BASE_URL%/}"
FAIL=0

# Guardrails: no editar _snapshot, base_portal debe tener block content
if [ -x "scripts/guardrails_check.sh" ]; then
  ./scripts/guardrails_check.sh || FAIL=1
fi

# Reutilizar smoke.sh (health, ready, /, /login, /signup, /portal/home, etc.)
if [ -x "scripts/smoke.sh" ]; then
  BASE_URL="$BASE_URL" START_SERVER="${START_SERVER:-0}" ./scripts/smoke.sh || FAIL=1
else
  # Fallback mínimo si smoke.sh no existe
  code=$(curl -s -o /dev/null -w "%{http_code}" "$BASE_URL/health" 2>/dev/null || echo "000")
  [ "$code" = "200" ] || { echo "FAIL GET /health -> $code"; FAIL=1; }
  code=$(curl -s -o /dev/null -w "%{http_code}" "$BASE_URL/login" 2>/dev/null || echo "000")
  [ "$code" = "200" ] || { echo "FAIL GET /login -> $code"; FAIL=1; }
fi

# Comprobar que /login devuelve HTML con contenido (no pantalla blanca)
if [ $FAIL -eq 0 ]; then
  body=$(curl -s -L "$BASE_URL/login" 2>/dev/null || true)
  if [ -z "$body" ] || [ "$(echo "$body" | wc -c)" -lt 200 ]; then
    echo "  FAIL GET /login: respuesta vacía o muy corta (posible pantalla blanca)"
    FAIL=1
  elif ! echo "$body" | grep -qi "html\|login\|iniciar\|sesión"; then
    echo "  WARN GET /login: respuesta sin texto esperado (revisar manualmente)"
  else
    echo "  OK GET /login: HTML con contenido"
  fi
fi

# Rutas adicionales del portal (sin cookie: 200/302/401 aceptables; no 500, no vacío)
for path in "/portal/invoices/issued" "/portal/invoices/received" "/portal/convertir-edo-cuenta" "/portal/summary"; do
  if [ $FAIL -eq 0 ]; then
    code=$(curl -s -o /tmp/smoke_portal_body$$ -w "%{http_code}" -L "$BASE_URL$path" 2>/dev/null || echo "000")
    if [ "$code" = "500" ]; then
      echo "  FAIL GET $path -> 500"
      FAIL=1
    elif [ "$code" = "200" ]; then
      body=$(cat /tmp/smoke_portal_body$$ 2>/dev/null || true)
      if [ -z "$body" ] || [ "$(echo "$body" | wc -c)" -lt 100 ]; then
        echo "  FAIL GET $path: cuerpo vacío o muy corto"
        FAIL=1
      elif ! echo "$body" | grep -qi "<title\|<html\|csrf-token\|portal"; then
        echo "  WARN GET $path: sin marcador HTML esperado"
      fi
    fi
    rm -f /tmp/smoke_portal_body$$
  fi
done

echo "---"
if [ $FAIL -eq 0 ]; then
  echo "OK: smoke portal pasado."
  exit 0
else
  echo "FAIL: uno o más checks fallaron."
  exit 1
fi
