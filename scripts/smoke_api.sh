#!/usr/bin/env bash
#
# Smoke test de APIs: /health, /status, /api/* (sin auth -> 401 es válido).
# Uso:
#   ./scripts/smoke_api.sh
#   BASE_URL=http://localhost:8000 ./scripts/smoke_api.sh
#
set -e
cd "$(dirname "$0")/.."
BASE_URL="${BASE_URL:-http://127.0.0.1:8000}"
BASE_URL="${BASE_URL%/}"
FAIL=0

run_curl() {
  local method="${1:-GET}"
  local path="$2"
  local expect_codes="$3"
  local url="${BASE_URL}${path}"
  local code
  code=$(curl -s -o /dev/null -w "%{http_code}" -X "$method" "$url" -H "Accept: application/json" 2>/dev/null || echo "000")
  for c in $expect_codes; do
    [ "$c" = "$code" ] && { echo "  OK $method $path -> $code"; return 0; }
  done
  echo "  FAIL $method $path -> $code (expected one of: $expect_codes)"
  return 1
}

echo "Smoke API: $BASE_URL"
echo "---"

# Health: 200 y JSON con status
if curl -s -H "Accept: application/json" "$BASE_URL/health" | grep -q '"status"' 2>/dev/null; then
  echo "  OK GET /health -> 200 (body ok)"
else
  run_curl GET "/health" "200" || FAIL=1
fi

# Status (HTML): 200
run_curl GET "/status" "200" || FAIL=1

# APIs que requieren sesión: 200 (con cookie) o 401 (sin cookie) son válidos
run_curl GET "/api/quick-invoice/bootstrap" "200 401" || FAIL=1
run_curl GET "/api/customers?limit=10" "200 401" || FAIL=1
run_curl GET "/api/products?limit=10" "200 401" || FAIL=1
run_curl GET "/api/account/status" "200 401" || FAIL=1
run_curl GET "/api/jobs?limit=5" "200 401" || FAIL=1

# Catálogos públicos (algunos pueden requerir issuer por cookie; 200 o 401)
run_curl GET "/api/catalogs/regimen_fiscal" "200 401" || FAIL=1

# Bancos (requiere auth)
run_curl GET "/api/bank/accounts" "200 401 404" || true

echo "---"
[ "$FAIL" -eq 0 ] && echo "OK (smoke API passed)" || { echo "FAIL (one or more checks failed)"; exit 1; }
