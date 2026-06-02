#!/usr/bin/env bash
# ────────────────────────────────────────────────────────────────
# smoke_prod.sh — Production smoke tests for ContaNeta
#
# Usage:
#   BASE_URL=https://YOUR_DOMAIN.com bash scripts/smoke_prod.sh
# ────────────────────────────────────────────────────────────────
set -euo pipefail

BASE_URL="${BASE_URL:-${1:-}}"
if [ -z "$BASE_URL" ]; then
    echo "Usage: BASE_URL=https://example.com bash scripts/smoke_prod.sh"
    echo "   or: bash scripts/smoke_prod.sh https://example.com"
    exit 1
fi
BASE_URL="${BASE_URL%/}"

PASS=0
FAIL=0

green()  { printf "\033[32m%s\033[0m\n" "$1"; }
red()    { printf "\033[31m%s\033[0m\n" "$1"; }

check() {
    local name="$1" expected="$2" url="$3"
    local code
    code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$url" 2>/dev/null || echo "000")
    if echo "$expected" | grep -q "$code"; then
        green "  PASS  $name ($code)"
        PASS=$((PASS + 1))
    else
        red "  FAIL  $name (got $code, expected $expected)"
        FAIL=$((FAIL + 1))
    fi
}

check_json() {
    local name="$1" key="$2" url="$3"
    local body
    body=$(curl -sf --max-time 10 "$url" 2>/dev/null || echo '{}')
    if echo "$body" | grep -q "$key"; then
        green "  PASS  $name"
        PASS=$((PASS + 1))
    else
        red "  FAIL  $name (key '$key' not found)"
        FAIL=$((FAIL + 1))
    fi
}

echo "============================================"
echo "  ContaNeta Production Smoke Tests"
echo "  Target: $BASE_URL"
echo "============================================"
echo

# ── Connectivity ──
echo "--- Connectivity ---"
if ! curl -sf --connect-timeout 5 "$BASE_URL/health" >/dev/null 2>&1; then
    red "  Server not reachable at $BASE_URL"
    exit 1
fi
green "  Server reachable"
echo

# ── HTTPS + SSL Cert ──
echo "--- HTTPS ---"
if [[ "$BASE_URL" == https://* ]]; then
    DOMAIN="${BASE_URL#https://}"
    DOMAIN="${DOMAIN%%/*}"
    SSL_EXPIRE=$(echo | openssl s_client -connect "${DOMAIN}:443" -servername "${DOMAIN}" 2>/dev/null | openssl x509 -noout -enddate 2>/dev/null | cut -d= -f2 || echo "unknown")
    green "  SSL certificate expires: $SSL_EXPIRE"
    PASS=$((PASS + 1))
    # Warn if cert expires within 30 days
    if [ "$SSL_EXPIRE" != "unknown" ]; then
        EXPIRE_EPOCH=$(date -j -f "%b %d %T %Y %Z" "$SSL_EXPIRE" "+%s" 2>/dev/null || date -d "$SSL_EXPIRE" "+%s" 2>/dev/null || echo 0)
        NOW_EPOCH=$(date "+%s")
        DAYS_LEFT=$(( (EXPIRE_EPOCH - NOW_EPOCH) / 86400 ))
        if [ "$DAYS_LEFT" -lt 30 ] 2>/dev/null; then
            red "  WARNING: SSL cert expires in $DAYS_LEFT days — renew soon!"
            FAIL=$((FAIL + 1))
        else
            green "  SSL cert valid for ~${DAYS_LEFT} days"
            PASS=$((PASS + 1))
        fi
    fi
else
    red "  WARNING: Not using HTTPS"
    FAIL=$((FAIL + 1))
fi
echo

# ── Health ──
echo "--- Health ---"
check_json "/health returns status:ok" '"status":"ok"\|"status": "ok"' "$BASE_URL/health"
check_json "/health DB readable" '"db_readable":true\|"db_readable": true' "$BASE_URL/health"
check_json "/health migrations applied" '"migrations_applied":true\|"migrations_applied": true' "$BASE_URL/health"
check_json "/health disk_ok" '"disk_ok":true\|"disk_ok": true' "$BASE_URL/health"
check_json "/health storage_writable" '"storage_writable":true\|"storage_writable": true' "$BASE_URL/health"
check "/ready returns 200" "200" "$BASE_URL/ready"
check "/status returns 200" "200" "$BASE_URL/status"
echo

# ── Public Pages ──
echo "--- Public Pages ---"
check "GET /" "200|302" "$BASE_URL/"
check "GET /login" "200" "$BASE_URL/login"
check "GET /signup" "200" "$BASE_URL/signup"
check "GET /pricing" "200|302" "$BASE_URL/pricing"
check "GET /privacy" "200" "$BASE_URL/privacy"
check "GET /terms" "200" "$BASE_URL/terms"
check "GET /cookies" "200|302" "$BASE_URL/cookies"
check "GET /forgot-password" "200" "$BASE_URL/forgot-password"
check "GET /robots.txt" "200" "$BASE_URL/robots.txt"
check "GET /sitemap.xml" "200" "$BASE_URL/sitemap.xml"
echo

# ── Auth Enforcement ──
echo "--- Auth Enforcement ---"
check "GET /portal/home (no auth → 302)" "302|401" "$BASE_URL/portal/home"
check "GET /api/customers (no auth → 401)" "401" "$BASE_URL/api/customers"
check "GET /admin (no auth → 401/403)" "401|403" "$BASE_URL/admin"
echo

# ── Security Headers ──
echo "--- Security Headers ---"
HEADERS=$(curl -sI --max-time 10 "$BASE_URL/health" 2>/dev/null)
if echo "$HEADERS" | grep -qi 'x-content-type-options'; then
    green "  PASS  X-Content-Type-Options present"
    PASS=$((PASS + 1))
else
    red "  FAIL  X-Content-Type-Options missing"
    FAIL=$((FAIL + 1))
fi
if echo "$HEADERS" | grep -qi 'x-frame-options'; then
    green "  PASS  X-Frame-Options present"
    PASS=$((PASS + 1))
else
    red "  FAIL  X-Frame-Options missing"
    FAIL=$((FAIL + 1))
fi
echo

# ── Dev Mode ──
echo "--- Dev Mode ---"
DEV_CODE=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "$BASE_URL/debug-oauth" 2>/dev/null)
if [ "$DEV_CODE" = "404" ] || [ "$DEV_CODE" = "405" ]; then
    green "  PASS  DEV_MODE is off (/debug-oauth → $DEV_CODE)"
    PASS=$((PASS + 1))
elif [ "$DEV_CODE" = "200" ]; then
    red "  FAIL  DEV_MODE appears to be ON — /debug-oauth returns 200"
    FAIL=$((FAIL + 1))
else
    green "  PASS  /debug-oauth → $DEV_CODE (not exposed)"
    PASS=$((PASS + 1))
fi
echo

# ── Summary ──
echo "============================================"
TOTAL=$((PASS + FAIL))
echo "  Results: $PASS passed, $FAIL failed (of $TOTAL)"
if [ "$FAIL" -gt 0 ]; then
    red "  PRODUCTION SMOKE: FAILED"
    exit 1
else
    green "  PRODUCTION SMOKE: PASSED"
fi
echo "============================================"
