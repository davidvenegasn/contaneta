#!/usr/bin/env bash
#
# P50 QA script automático — ~5 min para saber si algo se rompió.
#
# Verifica:
#   - GET /health y GET /ready → 200
#   - GET /portal/home sin cookie → 302 a /login (obligatorio si ENV=prod)
#   - Opcional: grep en LOG_FILE si está definido (errores recientes)
#
# Uso:
#   ./scripts/qa_portal_smoke.sh
#   BASE_URL=https://mi-app.example.com ./scripts/qa_portal_smoke.sh
#   ENV=prod BASE_URL=http://127.0.0.1:8000 ./scripts/qa_portal_smoke.sh
#
set -e
cd "$(dirname "$0")/.."
BASE_URL="${BASE_URL:-http://127.0.0.1:8000}"
BASE_URL="${BASE_URL%/}"
ENV="${ENV:-}"
FAIL=0

echo "QA Portal Smoke — $BASE_URL (ENV=${ENV:-<no set>})"
echo "---"

# --- 1. /health → 200 ---
code=$(curl -s -o /dev/null -w "%{http_code}" "$BASE_URL/health" 2>/dev/null || echo "000")
if [ "$code" = "200" ]; then
  echo "  OK GET /health -> 200"
else
  echo "  FAIL GET /health -> $code (expected 200)"
  FAIL=1
fi

# --- 2. /ready → 200 ---
code=$(curl -s -o /dev/null -w "%{http_code}" "$BASE_URL/ready" 2>/dev/null || echo "000")
if [ "$code" = "200" ]; then
  echo "  OK GET /ready -> 200"
else
  echo "  FAIL GET /ready -> $code (expected 200)"
  FAIL=1
fi

# --- 3. /portal/home sin cookie: 302 a /login (obligatorio en prod) ---
headers=$(curl -s -D - -o /dev/null -H "Accept: text/html" "$BASE_URL/portal/home" 2>/dev/null || true)
code=$(echo "$headers" | head -1 | awk '{print $2}')
location=$(echo "$headers" | grep -i "^Location:" | head -1 | tr -d '\r' | sed 's/Location: *//i')

if [ "$ENV" = "prod" ]; then
  if [ "$code" = "302" ] && echo "$location" | grep -q "/login"; then
    echo "  OK GET /portal/home (no cookie) -> 302 -> /login (ENV=prod)"
  else
    echo "  FAIL GET /portal/home (no cookie) -> $code, Location: $location (ENV=prod: expected 302 to /login)"
    FAIL=1
  fi
else
  if [ "$code" = "302" ] && echo "$location" | grep -q "/login"; then
    echo "  OK GET /portal/home (no cookie) -> 302 -> /login"
  elif [ "$code" = "200" ]; then
    echo "  OK GET /portal/home (no cookie) -> 200 (demo o dev)"
  else
    echo "  WARN GET /portal/home (no cookie) -> $code, Location: $location (se esperaba 200 o 302 a /login)"
  fi
fi

# --- 4. Opcional: grep logs si LOG_FILE está definido ---
if [ -n "${LOG_FILE:-}" ] && [ -f "$LOG_FILE" ]; then
  err_count=$(tail -n 500 "$LOG_FILE" 2>/dev/null | grep -c -E "ERROR|CRITICAL" || true)
  if [ "${err_count:-0}" -gt 0 ]; then
    echo "  WARN LOG_FILE: $err_count líneas con ERROR/CRITICAL en últimas 500"
  else
    echo "  OK LOG_FILE: sin ERROR/CRITICAL en últimas 500 líneas"
  fi
else
  echo "  (skip) LOG_FILE no definido o no existe — no se revisan logs"
fi

echo "---"
if [ $FAIL -eq 0 ]; then
  echo "OK: QA smoke pasado."
  exit 0
else
  echo "FAIL: uno o más checks fallaron."
  exit 1
fi
