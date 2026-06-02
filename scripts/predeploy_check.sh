#!/usr/bin/env bash
# ────────────────────────────────────────────────────────────────
# predeploy_check.sh — Pre-deployment validation for ContaNeta
#
# Run before every deploy. Exits 1 if ANY check fails → block deploy.
#
# Usage:
#   bash scripts/predeploy_check.sh
# ────────────────────────────────────────────────────────────────
set -euo pipefail

PASS=0
FAIL=0
WARN=0

green()  { printf "\033[32m  PASS  %s\033[0m\n" "$1"; }
red()    { printf "\033[31m  FAIL  %s\033[0m\n" "$1"; }
yellow() { printf "\033[33m  WARN  %s\033[0m\n" "$1"; }

pass() { green "$1"; PASS=$((PASS + 1)); }
fail() { red "$1"; FAIL=$((FAIL + 1)); }
warn() { yellow "$1"; WARN=$((WARN + 1)); }

echo "============================================"
echo "  ContaNeta Pre-Deploy Checks"
echo "============================================"
echo

# ── 1. Python version ──
echo "--- Python ---"
PY_VERSION=$(.venv/bin/python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || echo "0.0")
PY_MAJOR=$(echo "$PY_VERSION" | cut -d. -f1)
PY_MINOR=$(echo "$PY_VERSION" | cut -d. -f2)
if [ "$PY_MAJOR" -ge 3 ] && [ "$PY_MINOR" -ge 11 ]; then
    pass "Python $PY_VERSION (>= 3.11)"
else
    fail "Python $PY_VERSION — need >= 3.11"
fi

# ── 2. SQLite version ──
SQLITE_VERSION=$(.venv/bin/python3 -c "import sqlite3; print(sqlite3.sqlite_version)" 2>/dev/null || echo "0.0.0")
SQLITE_MINOR=$(echo "$SQLITE_VERSION" | cut -d. -f2)
if [ "$SQLITE_MINOR" -ge 35 ] 2>/dev/null; then
    pass "SQLite $SQLITE_VERSION (>= 3.35)"
else
    warn "SQLite $SQLITE_VERSION — recommend >= 3.35 for RETURNING"
fi
echo

# ── 3. App imports ──
echo "--- App Import ---"
if .venv/bin/python3 -c "import app; print('OK')" >/dev/null 2>&1; then
    pass "import app OK"
else
    fail "import app FAILED"
fi
echo

# ── 4. Tests ──
echo "--- Tests ---"
TEST_OUTPUT=$(.venv/bin/pytest -q 2>&1 || true)
if echo "$TEST_OUTPUT" | grep -q "passed"; then
    PASSED=$(echo "$TEST_OUTPUT" | grep -oE '[0-9]+ passed' | grep -oE '[0-9]+')
    FAILED_T=$(echo "$TEST_OUTPUT" | grep -oE '[0-9]+ failed' | grep -oE '[0-9]+' || echo "0")
    if [ "${FAILED_T:-0}" = "0" ] || [ -z "$FAILED_T" ]; then
        pass "pytest: $PASSED passed, 0 failed"
    else
        fail "pytest: $PASSED passed, $FAILED_T failed"
    fi
else
    fail "pytest did not run successfully"
fi
echo

# ── 5. Environment variables ──
echo "--- Environment (.env) ---"
if [ -f .env ]; then
    REQUIRED_VARS="SESSION_SECRET APP_DB_PATH SITE_URL"
    for var in $REQUIRED_VARS; do
        if grep -q "^${var}=" .env 2>/dev/null; then
            pass "$var present in .env"
        else
            fail "$var missing from .env"
        fi
    done
    OPTIONAL_VARS="STRIPE_SECRET_KEY STRIPE_WEBHOOK_SECRET SENTRY_DSN"
    for var in $OPTIONAL_VARS; do
        if grep -q "^${var}=" .env 2>/dev/null; then
            pass "$var present"
        else
            warn "$var not configured (optional)"
        fi
    done
else
    warn ".env file not found (using env vars directly)"
fi
echo

# ── 6. Storage writable ──
echo "--- Storage ---"
STORAGE_DIR="${STORAGE_DIR:-storage}"
if [ -d "$STORAGE_DIR" ] && [ -w "$STORAGE_DIR" ]; then
    pass "storage/ is writable"
else
    warn "storage/ not found or not writable"
fi
echo

# ── 7. File size audit ──
echo "--- File Size Audit (>350 lines) ---"
OVER_LIMIT=$(find . -name "*.py" -not -path "./.venv/*" -not -path "./_archive/*" -not -path "./migrations/*" -exec awk 'END{if(NR>350) print FILENAME": "NR" lines"}' {} \; 2>/dev/null || true)
if [ -n "$OVER_LIMIT" ]; then
    warn "Files over 350 lines:"
    echo "$OVER_LIMIT" | while read -r line; do
        echo "    $line"
    done
else
    pass "No source files exceed 350 lines"
fi
echo

# ── Summary ──
echo "============================================"
TOTAL=$((PASS + FAIL + WARN))
echo "  Results: $PASS passed, $FAIL failed, $WARN warnings (of $TOTAL)"
if [ "$FAIL" -gt 0 ]; then
    red "PRE-DEPLOY: BLOCKED — fix $FAIL failures before deploying"
    exit 1
else
    green "PRE-DEPLOY: READY"
fi
echo "============================================"
