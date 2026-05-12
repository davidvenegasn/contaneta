# Rate Limiting Audit — ContaNeta

**Date:** 2026-05-12

## Implementation

- **Storage**: SQLite `rate_limit_attempts` table (persistent, multi-worker safe)
- **Tracking**: Per-IP via sliding time windows
- **Key format**: `{prefix}:{client_ip}` (e.g., `login:192.168.1.1`)
- **Defaults**: 10 attempts per 60 seconds
- **Cleanup**: Startup only (24h retention)

## Protected Endpoints

| Endpoint | Key | Limit | Window |
|----------|-----|-------|--------|
| POST /login | login | 10 | 60s |
| GET /login?token= | token_login | 20 | 60s |
| POST /auth/signup | register | 10 | 60s |
| POST /forgot | forgot | 10 | 60s |
| POST /reset-password | reset | 10 | 60s |
| POST /api/invoices/create | api_invoice | 20 | 60s |
| POST /api/invoices/cancel | api_invoice_cancel | 5 | 60s |
| POST /api/invoices/bulk-issue | api_bulk_issue | 5 | 60s |
| POST /api/quotations/create | api_quotation | 20 | 60s |
| POST /sat/upload | upload | 10 | 60s |
| POST /sat/sync | sat_sync | 10 | 60s |
| POST /bank/* (ingest, reconcile, etc.) | bank_* | 10 | 60s |

## Unprotected Endpoints (Gaps)

| Endpoint | Risk | Priority |
|----------|------|----------|
| GET /verify-email?token= | Token brute-force | HIGH |
| OAuth callbacks | Replay/spam | MEDIUM |
| POST /public/cotizacion/respond | Spam responses | MEDIUM |
| POST /billing/checkout | Checkout session flood | LOW |
| GET endpoints (lists/reads) | Enumeration | LOW |

## Concerns

### Security
1. **X-Forwarded-For spoofing** — Takes first IP without validating trusted proxies
2. **No per-user limiting** — All IP-based; authenticated endpoints should also limit by user_id
3. **Unprotected email verification** — Token endpoint has no rate limit

### Operational
4. **No periodic cleanup** — `rate_limit_attempts` grows unbounded between restarts
5. **DB contention** — Each check uses `BEGIN IMMEDIATE` (potential bottleneck under load)
6. **No RateLimit headers** — Clients can't adjust request rate

## Recommendations

### Immediate (Do Now)
- Add rate limit to `/verify-email` endpoint
- Schedule periodic cleanup (hourly) via worker or APScheduler

### High Priority
- Validate X-Forwarded-For against trusted proxy list
- Add rate limits to public-facing POST endpoints
- Add standard `RateLimit-*` response headers

### Medium Priority
- Per-user rate limiting for authenticated endpoints
- Monitor `rate_limit_attempts` table size
- Document strategy in CLAUDE.md
