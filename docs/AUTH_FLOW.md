# Authentication Flow — ContaNeta

## Overview

Cookie-based stateless sessions with HMAC-SHA256 signing. No server-side session store — all state is in the signed cookie.

## Session Format

```
Base64url( "user_id|issuer_id|expiry[|restore_issuer_id]" + "." + HMAC-SHA256(payload, SESSION_SECRET) )
```

| Parts | Meaning |
|-------|---------|
| 2-part | Legacy: `issuer_id\|expiry` (user_id=0, token-based login) |
| 3-part | Standard: `user_id\|issuer_id\|expiry` |
| 4-part | Impersonation: `user_id\|issuer_id\|expiry\|restore_issuer_id` |

- **Cookie name:** `portal_session`
- **TTL:** 7 days (configurable via `SESSION_TTL_DAYS`)
- **Cookie flags:** `HttpOnly=True`, `SameSite=Lax`, `Secure=True` (auto-detected from HTTPS)

## Flows

### Registration (`POST /auth/signup` or `POST /auth/register`)

```
1. Validate CSRF token
2. Rate limit check (10 attempts/60s per IP)
3. Sanitize email, validate password (>= 8 chars)
4. Sanitize RFC, validate razon_social
5. Check email not already registered (generic error if exists)
6. Create user (bcrypt password hash)
7. Create issuer + membership (role=owner)
8. Send verification email (or log to console if DEV_MODE + no SMTP)
9. Set session cookie -> redirect /portal/home
```

### Login (`POST /login`)

```
1. Validate CSRF token (skipped in DEV_MODE for convenience)
2. Rate limit check (10/60s per IP)
3. Resolve user by email or phone
4. Verify bcrypt password hash
5. Per-email cooldown tracking (effectively disabled: 99999 max failures)
6. Check memberships:
   - 0 memberships -> redirect /confirmar-perfil
   - 1 membership  -> set cookie with issuer_id -> redirect /portal/home
   - N memberships -> set cookie with issuer_id=0 -> redirect /choose-issuer
7. Audit log: action=login
```

### Token Login (`GET /login?token=<issuer_token>`)

```
1. Rate limit: 20 attempts/60s per IP
2. Look up issuer by token in issuer_tokens table
3. Set session cookie (user_id=0, legacy mode)
4. Redirect /portal/home
```

### Password Reset

```
1. POST /forgot -> validate CSRF, rate limit, sanitize email
2. If user exists: create token (SHA-256 hashed in DB), send email
3. Always show "enlace enviado" (doesn't reveal if email exists)
4. GET /reset-password?token=<token> -> show form
5. POST /reset-password -> validate CSRF, rate limit
   - Consume token (single-use: marks used_at)
   - Token expires in 2 hours
   - Validate password >= 8 chars, confirmation matches
   - Update password hash + set password_changed_at
   - Redirect /login?reset=1
```

### Session Invalidation

- **Password change:** Sessions created before `password_changed_at` are rejected
  - Mechanism: session expiry timestamp encodes creation time (`created_at = expiry - TTL`)
  - On each request, `get_portal_issuer()` checks `password_changed_at > session_created_at`
- **Logout:** Cookie deleted with same parameters (path, samesite, secure)
- **Expiry:** 7-day TTL enforced in `verify_session()`
- **SECRET rotation:** Changing `SESSION_SECRET` invalidates ALL sessions

### OAuth (Google, Facebook)

```
1. GET /login -> user clicks Google/Facebook button
2. Redirect to OAuth provider with client_id + redirect_uri
3. Callback: exchange code for access_token
4. Fetch user info (email, name, oauth_id)
5. get_or_create_user_by_oauth() -> find/create user
6. Set session cookie -> redirect /portal/home or /confirmar-perfil
```

## Authentication Dependency

All portal/API routes use `Depends(get_portal_issuer)` which:

1. Checks `?token=` query param (rate-limited)
2. Verifies session cookie (HMAC signature + expiry)
3. Validates password hasn't changed since session was created
4. Resolves membership (user -> issuer mapping with role)
5. Falls back to demo issuer only if `DEV_MODE=1` AND `ALLOW_DEMO_PORTAL=1`
6. Sets `request.state.{issuer_id, user_id, membership_role, is_impersonating}`

## Security Properties

| Property | Implementation | File |
|----------|---------------|------|
| Password hashing | bcrypt (with salt) | `services/users.py` |
| Session signing | HMAC-SHA256 | `services/session.py` |
| CSRF protection | Timestamped HMAC tokens, 1h TTL | `services/csrf.py` |
| Rate limiting | In-memory sliding window, per IP | `services/rate_limit.py` |
| Cookie security | HttpOnly, SameSite=Lax, Secure (HTTPS) | `services/session.py` |
| Error messages | Generic (don't reveal email existence) | `routers/auth.py` |
| Password reset | Single-use, 2h expiry, SHA-256 hashed in DB | `services/verification.py` |
| Session invalidation | Rejected if created before password_changed_at | `routers/deps.py` |
| Admin impersonation | 4-part cookie with restore_issuer_id, audit logged | `routers/deps.py` |

## Rate Limits

| Action | Window | Max Attempts | Key |
|--------|--------|-------------|-----|
| Login | 60s | 10 | `login:<IP>` |
| Register | 60s | 10 | `register:<IP>` |
| Forgot password | 60s | 10 | `forgot:<IP>` |
| Reset password | 60s | 10 | `reset:<IP>` |
| Token login | 60s | 20 | `token:<IP>` |
| FIEL upload | 60s | 10 | `fiel_upload:<IP>` |
| SAT sync | 60s | 5 | `sat_sync:<IP>` |

**Limitation:** In-memory only. Resets on app restart. Not shared across workers. Acceptable for single-process deployments.

## Environment Variables

| Variable | Required | Default | Purpose |
|----------|----------|---------|---------|
| `SESSION_SECRET` | **Prod: YES** | dev fallback | HMAC signing key (64-char hex) |
| `SESSION_TTL_DAYS` | No | 7 | Cookie/session lifetime |
| `SESSION_COOKIE_NAME` | No | `portal_session` | Cookie name |
| `COOKIE_SECURE` | No | 1 (prod) | Force Secure flag |
| `DEV_MODE` | No | 0 (prod) | Enables dev features |
| `ALLOW_DEMO_PORTAL` | No | 0 | Allow unauthenticated demo access |
