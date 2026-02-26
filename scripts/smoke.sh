#!/usr/bin/env bash
#
# Smoke test: pega endpoints clave y verifica 200/302.
# Uso:
#   ./scripts/smoke.sh                    # App ya corriendo en http://127.0.0.1:8000
#   BASE_URL=http://localhost:8000 ./scripts/smoke.sh
#   START_SERVER=1 ./scripts/smoke.sh      # Levanta la app en background y luego prueba
#
set -e
cd "$(dirname "$0")/.."
BASE_URL="${BASE_URL:-http://127.0.0.1:8000}"
# Quitar barra final si la tiene
BASE_URL="${BASE_URL%/}"
FAIL=0
START_SERVER="${START_SERVER:-0}"
SERVER_PID=""

cleanup() {
  if [ -n "$SERVER_PID" ] && kill -0 "$SERVER_PID" 2>/dev/null; then
    kill "$SERVER_PID" 2>/dev/null || true
    wait "$SERVER_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT

run_curl() {
  local method="${1:-GET}"
  local path="$2"
  local expect_codes="$3"
  local url="${BASE_URL}${path}"
  local code c
  code=$(curl -s -o /dev/null -w "%{http_code}" -X "$method" "$url" 2>/dev/null || echo "000")
  for c in $expect_codes; do
    [ "$c" = "$code" ] && { echo "  OK $method $path -> $code"; return 0; }
  done
  echo "  FAIL $method $path -> $code (expected one of: $expect_codes)"
  return 1
}

if [ "$START_SERVER" = "1" ]; then
  PORT="${PORT:-8000}"
  BASE_URL="http://127.0.0.1:${PORT}"
  echo "Iniciando servidor en $BASE_URL ..."
  if [ -x ".venv/bin/python" ]; then
    .venv/bin/python -m uvicorn app:app --host 127.0.0.1 --port "$PORT" & SERVER_PID=$!
  else
    python3 -m uvicorn app:app --host 127.0.0.1 --port "$PORT" & SERVER_PID=$!
  fi
  # Esperar a que responda
  for i in 1 2 3 4 5 6 7 8 9 10; do
    if curl -s -o /dev/null -w "%{http_code}" "$BASE_URL/health" 2>/dev/null | grep -q 200; then
      echo "Servidor listo."
      break
    fi
    [ $i -eq 10 ] && { echo "Timeout esperando servidor."; exit 1; }
    sleep 1
  done
fi

echo "Smoke test: $BASE_URL"
echo "---"

# Health: 200 y body con "ok"
if curl -s "$BASE_URL/health" | grep -q '"status"' && curl -s -o /dev/null -w "%{http_code}" "$BASE_URL/health" | grep -q 200; then
  echo "  OK GET /health -> 200"
else
  echo "  FAIL GET /health (expected 200 and status in body)"
  FAIL=1
fi
# Ready: 200 si migraciones aplicadas
run_curl GET "/ready" "200" || FAIL=1

# Raíz: redirección (302 o 307)
run_curl GET "/" "302 307" || FAIL=1
run_curl GET "/login" "200" || FAIL=1
run_curl GET "/signup" "200" || FAIL=1
run_curl GET "/register" "302" || FAIL=1
# Portal sin cookie: 302 a login (Accept: text/html) o 401 (curl default); con cookie: 200
run_curl GET "/portal/home" "200 302 401" || FAIL=1
run_curl GET "/portal/info" "200 302 401" || FAIL=1
run_curl GET "/logout" "302" || FAIL=1

echo "---"
if [ $FAIL -eq 0 ]; then
  echo "OK: smoke test pasado."
  exit 0
else
  echo "FAIL: uno o más checks fallaron."
  exit 1
fi
