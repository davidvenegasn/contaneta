# Session & Cookie Security Audit — ContaNeta

**Date:** 2026-05-12

## Session Cookie

| Property | Value | Status |
|----------|-------|--------|
| Cookie name | `portal_session` | ✅ |
| HttpOnly | `True` (always) | ✅ Prevents JS access |
| SameSite | `Lax` | ✅ CSRF protection |
| Secure | `True` in prod (HTTPS), `False` in dev (HTTP) | ✅ |
| Max-Age | `SESSION_TTL_DAYS * 86400` (default 7 days) | ✅ |
| Path | `/` | ✅ |

## Signature

- **Algorithm**: HMAC-SHA256 with `SESSION_SECRET`
- **Format**: base64url(`{payload}.{hex_signature}`)
- **Payload**: `user_id|issuer_id|expiry[|restore_issuer_id]`
- **Constant-time compare**: YES — uses `hmac.compare_digest()` (line 57)
- **Expiry check**: YES — `time.time() > expiry` returns None

## CSRF

- **File**: `services/auth/csrf.py`
- **Token format**: HMAC-based with 1-hour TTL
- **Validation**: Required on all POST handlers via `csrf_service.verify_api_csrf(request)`

## Findings

| Check | Status | Notes |
|-------|--------|-------|
| HMAC-SHA256 signature | ✅ | `hmac.new(SECRET, payload, sha256)` |
| Constant-time compare | ✅ | `hmac.compare_digest()` |
| Expiry enforced | ✅ | 7-day default, configurable via `SESSION_TTL_DAYS` |
| HttpOnly flag | ✅ | Always set |
| Secure flag in prod | ✅ | Set when HTTPS detected |
| SameSite=Lax | ✅ | CSRF protection |
| SESSION_SECRET required in prod | ✅ | RuntimeError if missing |
| Secret rotation on password change | ❌ | No session invalidation on password change |

## Recommendation

**Session invalidation on password change**: Currently, changing a password does not invalidate existing sessions. An attacker with a stolen cookie could continue accessing the account after the password is changed. Consider adding a session version counter or tracking session creation time against last password change time.

**Risk**: LOW-MEDIUM. Mitigated by 7-day TTL and HMAC integrity.
