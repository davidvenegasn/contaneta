# Tenant Isolation Audit — ContaNeta

**Date:** 2026-05-12 | **Auditor:** Claude Code | **Status:** PASS (no critical findings)

## Summary

All ~80+ endpoints audited. Every tenant-scoped query includes `issuer_id = ?` from the HMAC-signed session cookie (via `get_portal_issuer()`). No endpoint accepts `issuer_id` from user input.

## Findings

| Finding | Severity | Detail |
|---------|----------|--------|
| Exchange rates table is global | LOW-MEDIUM | Any authenticated user can write rates affecting all tenants. Consider adding `issuer_id` or admin-only gating on write. |

**No CRITICAL or HIGH findings.**

## Audit Coverage

| Module | Endpoints | Isolation Status |
|--------|-----------|-----------------|
| routers/api/invoices.py | 17 | ✅ All use session issuer_id |
| routers/api/customers.py | 5 | ✅ All use session issuer_id |
| routers/api/products.py | 4 | ✅ All use session issuer_id |
| routers/api/quotations.py | 4 | ✅ All use session issuer_id |
| routers/api/providers.py | 2 | ✅ All use session issuer_id |
| routers/api/operations.py | 15+ | ✅ All use session issuer_id |
| routers/api/account.py | 3 | ✅ All use session issuer_id |
| routers/api/catalogs.py | 6 | N/A (shared SAT reference data) |
| routers/portal/invoices.py | 14 | ✅ All use session issuer_id |
| routers/portal/dashboard.py | 6 | ✅ All use session issuer_id |
| routers/portal/catalogs.py | 13 | ✅ All use session issuer_id |
| routers/portal/bank.py | 25 | ✅ All use session issuer_id |
| routers/portal/quotations.py | 5 | ✅ All use session issuer_id |
| routers/portal/sat_config.py | 5 | ✅ All use session issuer_id |
| routers/portal/month_close.py | 7 | ✅ All use session issuer_id |
| routers/portal/misc.py | 4 | ✅ All use session issuer_id |
| routers/admin.py | 10+ | N/A (cross-tenant by design, admin role required) |
| routers/public.py | 5 | N/A (public, token-based access) |

## Verification Patterns

1. **Session-derived issuer_id**: All `Depends(get_portal_issuer)` resolve `issuer_id` from HMAC-signed cookie — cannot be spoofed
2. **Compound WHERE clauses**: Path params (UUID, ID) always combined with `issuer_id` (e.g., `WHERE uuid = ? AND issuer_id = ?`)
3. **File downloads**: DB lookup verifies `issuer_id` before serving files; path traversal checks via `_safe_abs_path()`
4. **Child records**: Accessed via parent IDs that are already verified against `issuer_id`
5. **No IDOR**: No endpoint accepts `issuer_id` from body/query/path to override session

## Exchange Rates Finding (Detail)

The `exchange_rates` table (`migrations/039_exchange_rates.sql`) has no `issuer_id` column. Three endpoints (`GET /api/exchange-rate`, `GET /api/exchange-rates`, `POST /api/exchange-rates`) are authenticated but operate on shared data.

**Risk**: A malicious tenant could set USD/MXN to an absurd value affecting all tenants' foreign invoice calculations.

**Recommendations**:
- Option A: Add `issuer_id` to `exchange_rates` table (tenant-specific rates)
- Option B: Restrict write endpoint to admin role only
- Option C: Accept as shared reference data (current behavior matches Banxico rates concept)
