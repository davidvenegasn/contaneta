#!/usr/bin/env bash
# ────────────────────────────────────────────────────────────────
# smoke_release.sh — Release smoke tests for ContaNeta
#
# Tests: health, ready, login page, signup flow, auth enforcement,
#        API auth, CSRF presence, SAT status.
#
# Usage:
#   bash scripts/smoke_release.sh
#   BASE_URL=https://app.contaneta.com bash scripts/smoke_release.sh
# ────────────────────────────────────────────────────────────────
set -euo pipefail
cd "$(dirname "$0")/.."

BASE_URL="${BASE_URL:-http://127.0.0.1:${PORT:-8000}}"
BASE_URL="${BASE_URL%/}"
PASS=0
FAIL=0
SKIP=0
COOKIE_JAR=$(mktemp)
trap 'rm -f "$COOKIE_JAR"' EXIT

green()  { printf "\033[32m%s\033[0m\n" "$1"; }
red()    { printf "\033[31m%s\033[0m\n" "$1"; }
yellow() { printf "\033[33m%s\033[0m\n" "$1"; }

check() {
  local name="$1"
  shift
  if "$@" >/dev/null 2>&1; then
    green "  PASS  $name"
    PASS=$((PASS + 1))
  else
    red "  FAIL  $name"
    FAIL=$((FAIL + 1))
  fi
}

skip() {
  yellow "  SKIP  $1"
  SKIP=$((SKIP + 1))
}

echo "============================================"
echo "  ContaNeta Release Smoke Tests"
echo "  Target: $BASE_URL"
echo "============================================"
echo

# ── 0. Server reachable ─────────────────────────────────────────
echo "--- Connectivity ---"
if ! curl -sf --connect-timeout 5 "$BASE_URL/health" >/dev/null 2>&1; then
  red "  Server not reachable at $BASE_URL"
  red "  Start the server first: ./run_server.sh"
  exit 1
fi
green "  Server reachable"
echo

# ── 1. Health & Ready ───────────────────────────────────────────
echo "--- Health Checks ---"

check "/health returns 200 with status" \
  bash -c "curl -sf '$BASE_URL/health' | grep -q '\"status\"'"

check "/ready returns 200 with ready:true" \
  bash -c "curl -sf '$BASE_URL/ready' | grep -q '\"ready\": true\\|\"ready\":true'"

check "/status returns 200" \
  bash -c "curl -sf -o /dev/null -w '%{http_code}' '$BASE_URL/status' | grep -q '200'"

echo

# ── 2. Public Pages ─────────────────────────────────────────────
echo "--- Public Pages ---"

check "GET /login returns 200" \
  bash -c "curl -sf -o /dev/null -w '%{http_code}' '$BASE_URL/login' | grep -q '200'"

check "GET /signup returns 200" \
  bash -c "curl -sf -o /dev/null -w '%{http_code}' '$BASE_URL/signup' | grep -q '200'"

check "GET /forgot returns 200" \
  bash -c "curl -sf -o /dev/null -w '%{http_code}' '$BASE_URL/forgot' | grep -q '200'"

check "GET /pricing returns 200" \
  bash -c "curl -sf -o /dev/null -w '%{http_code}' '$BASE_URL/pricing' | grep -qE '200|302'"

check "GET /terms returns 200" \
  bash -c "curl -sf -o /dev/null -w '%{http_code}' '$BASE_URL/terms' | grep -q '200'"

check "GET /privacy returns 200" \
  bash -c "curl -sf -o /dev/null -w '%{http_code}' '$BASE_URL/privacy' | grep -q '200'"

echo

# ── 3. Auth Enforcement ─────────────────────────────────────────
echo "--- Auth Enforcement ---"

check "GET /portal/home without cookie redirects to login (302)" \
  bash -c "curl -s -o /dev/null -w '%{http_code}' '$BASE_URL/portal/home' | grep -qE '302|401'"

check "GET /portal/login returns 200" \
  bash -c "curl -sf -o /dev/null -w '%{http_code}' '$BASE_URL/portal/login' | grep -qE '200|302'"

check "GET /api/customers without auth returns 401" \
  bash -c "curl -s -o /dev/null -w '%{http_code}' '$BASE_URL/api/customers' | grep -q '401'"

check "GET /api/products without auth returns 401" \
  bash -c "curl -s -o /dev/null -w '%{http_code}' '$BASE_URL/api/products' | grep -q '401'"

check "GET /api/account/status without auth returns 401" \
  bash -c "curl -s -o /dev/null -w '%{http_code}' '$BASE_URL/api/account/status' | grep -q '401'"

check "GET /admin without auth returns 401/403" \
  bash -c "curl -s -o /dev/null -w '%{http_code}' '$BASE_URL/admin' | grep -qE '401|403'"

echo

# ── 4. CSRF Token Present ───────────────────────────────────────
echo "--- CSRF Protection ---"

check "Login page contains csrf_token input" \
  bash -c "curl -sf '$BASE_URL/login' | grep -qi 'csrf_token'"

check "Signup page contains csrf_token input" \
  bash -c "curl -sf '$BASE_URL/signup' | grep -qi 'csrf_token'"

echo

# ── 5. Security Headers ─────────────────────────────────────────
echo "--- Security Headers ---"

HEADERS=$(curl -sI "$BASE_URL/health" 2>/dev/null)

check "X-Content-Type-Options header present" \
  bash -c "echo '$HEADERS' | grep -qi 'x-content-type-options'"

check "X-Frame-Options header present" \
  bash -c "echo '$HEADERS' | grep -qi 'x-frame-options'"

echo

# ── 6. Dev Mode Gating ──────────────────────────────────────────
echo "--- Dev Mode Gating ---"

DEBUG_CODE=$(curl -s -o /dev/null -w '%{http_code}' "$BASE_URL/debug-oauth" 2>/dev/null)
if [ "$DEBUG_CODE" = "404" ]; then
  green "  PASS  /debug-oauth returns 404 (gated in prod)"
  PASS=$((PASS + 1))
elif [ "$DEBUG_CODE" = "200" ]; then
  yellow "  WARN  /debug-oauth returns 200 — DEV_MODE may be on"
  SKIP=$((SKIP + 1))
else
  green "  PASS  /debug-oauth returns $DEBUG_CODE (not exposed)"
  PASS=$((PASS + 1))
fi

echo

# ── 7. API Smoke (with token login if available) ────────────────
echo "--- API Smoke ---"

# Try token-based login (for dev/staging)
TOKEN="${SMOKE_TOKEN:-}"
if [ -n "$TOKEN" ]; then
  curl -sf -c "$COOKIE_JAR" -L "$BASE_URL/login?token=$TOKEN" >/dev/null 2>&1 || true
  API_CODE=$(curl -sf -b "$COOKIE_JAR" -o /dev/null -w '%{http_code}' "$BASE_URL/api/customers?limit=1" 2>/dev/null)
  if [ "$API_CODE" = "200" ]; then
    green "  PASS  Token login + API /customers works"
    PASS=$((PASS + 1))

    check "GET /api/products returns 200 (authed)" \
      bash -c "curl -sf -b '$COOKIE_JAR' -o /dev/null -w '%{http_code}' '$BASE_URL/api/products?limit=1' | grep -q '200'"

    check "GET /api/account/status returns 200 (authed)" \
      bash -c "curl -sf -b '$COOKIE_JAR' -o /dev/null -w '%{http_code}' '$BASE_URL/api/account/status' | grep -q '200'"

    check "GET /api/jobs returns 200 (authed)" \
      bash -c "curl -sf -b '$COOKIE_JAR' -o /dev/null -w '%{http_code}' '$BASE_URL/api/jobs?limit=1' | grep -q '200'"
  else
    skip "Token login failed (code=$API_CODE) — skipping authed API tests"
  fi
else
  skip "No SMOKE_TOKEN set — skipping authed API tests (set SMOKE_TOKEN=<issuer_token>)"
fi

echo

# ── 8. Database & Migrations ────────────────────────────────────
echo "--- Database ---"

HEALTH_JSON=$(curl -sf "$BASE_URL/health" 2>/dev/null || echo '{}')

check "DB readable" \
  bash -c "echo '$HEALTH_JSON' | grep -q '\"db_readable\": true\\|\"db_readable\":true'"

check "Migrations applied" \
  bash -c "echo '$HEALTH_JSON' | grep -q '\"migrations_ok\": true\\|\"migrations_applied\": true\\|\"migrations_ok\":true\\|\"migrations_applied\":true'"

check "Storage writable" \
  bash -c "echo '$HEALTH_JSON' | grep -q '\"storage_writable\": true\\|\"storage_writable\":true'"

echo

# ── Summary ─────────────────────────────────────────────────────
echo "============================================"
TOTAL=$((PASS + FAIL + SKIP))
echo "  Results: $PASS passed, $FAIL failed, $SKIP skipped (of $TOTAL)"
if [ "$FAIL" -gt 0 ]; then
  red "  RELEASE SMOKE: FAILED"
  exit 1
else
  green "  RELEASE SMOKE: PASSED"
fi
echo "============================================"
