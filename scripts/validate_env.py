#!/usr/bin/env python3
"""Validate environment variables for ContaNeta deployment.

Usage:
    python scripts/validate_env.py          # Check current .env
    ENV=prod python scripts/validate_env.py # Simulate production checks
"""
import os
import sys

from dotenv import load_dotenv

load_dotenv(override=True)

ENV = (os.getenv("ENV") or "dev").strip().lower()
IS_PROD = ENV == "prod"

errors = []
warnings = []


def require(var: str, msg: str = ""):
    val = (os.getenv(var) or "").strip()
    if not val:
        errors.append(f"MISSING: {var}" + (f" — {msg}" if msg else ""))
    return val


def recommend(var: str, msg: str = ""):
    val = (os.getenv(var) or "").strip()
    if not val:
        warnings.append(f"RECOMMENDED: {var}" + (f" — {msg}" if msg else ""))
    return val


print(f"Validating environment for ENV={ENV} (IS_PROD={IS_PROD})")
print("=" * 60)

# Always required
require("APP_DB_PATH", "SQLite database path (default: ./invoicing.db)")

if IS_PROD:
    # Production requirements
    require("SESSION_SECRET", "Generate: python3 -c \"import secrets; print(secrets.token_hex(32))\"")
    require("AT_REST_MASTER_KEY", "Required for FIEL encryption. Generate same way as SESSION_SECRET.")
    require("SITE_URL", "Base URL for redirects (e.g., https://contaneta.com)")

    # Stripe (required if billing is active)
    stripe_key = os.getenv("STRIPE_SECRET_KEY", "").strip()
    if stripe_key:
        require("STRIPE_WEBHOOK_SECRET", "Required when Stripe is configured")
        require("STRIPE_PRICE_ID", "Required when Stripe is configured")
        recommend("SITE_URL", "Needed for Stripe checkout redirects")

    # Security
    dev_mode = os.getenv("DEV_MODE", "0")
    if dev_mode == "1":
        errors.append("DEV_MODE=1 in production — must be 0")
    demo = os.getenv("ALLOW_DEMO_PORTAL", "0")
    if demo == "1":
        errors.append("ALLOW_DEMO_PORTAL=1 in production — must be 0")
    legacy = os.getenv("ALLOW_LEGACY_TOKEN_LOGIN", "0")
    if legacy == "1":
        warnings.append("ALLOW_LEGACY_TOKEN_LOGIN=1 in production — consider disabling")

    recommend("COOKIE_SECURE", "Should be 1 in production (HTTPS)")
else:
    # Dev recommendations
    recommend("SESSION_SECRET", "Set to avoid session invalidation on restart")

# Database path check
db_path = os.getenv("APP_DB_PATH", "./invoicing.db")
if not os.path.isfile(db_path):
    warnings.append(f"DB file not found at {db_path} (will be created on first run)")

# Session TTL
ttl = os.getenv("SESSION_TTL_DAYS", "7")
try:
    ttl_int = int(ttl)
    if ttl_int > 30:
        warnings.append(f"SESSION_TTL_DAYS={ttl_int} — consider shorter TTL for security")
except ValueError:
    errors.append(f"SESSION_TTL_DAYS={ttl} — must be integer")

# Report
print()
if errors:
    print(f"ERRORS ({len(errors)}):")
    for e in errors:
        print(f"  ✗ {e}")
    print()

if warnings:
    print(f"WARNINGS ({len(warnings)}):")
    for w in warnings:
        print(f"  ⚠ {w}")
    print()

if not errors and not warnings:
    print("All checks passed.")

if errors:
    print(f"\nFAILED: {len(errors)} error(s) must be fixed before deployment.")
    sys.exit(1)
else:
    print(f"\nPASSED: {len(warnings)} warning(s), 0 errors.")
    sys.exit(0)
