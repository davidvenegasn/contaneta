# HTTP Security Headers Audit — ContaNeta

**Date:** 2026-05-12

## Present Headers

| Header | Value | Status |
|--------|-------|--------|
| X-Content-Type-Options | `nosniff` | ✅ |
| X-Frame-Options | `DENY` | ✅ |
| Referrer-Policy | `strict-origin-when-cross-origin` | ✅ |
| Permissions-Policy | `geolocation=(), microphone=(), camera=(), payment=(), usb=(), serial=()` | ✅ |
| Content-Security-Policy | See below | ✅ |
| X-Request-ID | UUID per request | ✅ |

## CSP Policy

```
default-src 'self';
base-uri 'self';
object-src 'none';
frame-ancestors 'none';
form-action 'self';
script-src 'self' 'unsafe-inline' https://js.stripe.com;
style-src 'self' 'unsafe-inline' https://fonts.googleapis.com;
font-src 'self' https://fonts.gstatic.com;
frame-src 'self' https://js.stripe.com https://hooks.stripe.com;
img-src 'self' data:;
connect-src 'self' https://api.stripe.com;
```

**Note:** `unsafe-inline` is required for script/style because Jinja2 templates use inline `<script>` and `<style>` blocks. Removing it would require refactoring all templates to use external files or nonce-based CSP.

## Missing Headers

| Header | Recommendation | Priority |
|--------|---------------|----------|
| Strict-Transport-Security | `max-age=31536000; includeSubDomains` | **HIGH** (add in Nginx/Caddy config for prod) |

**HSTS should be set at the reverse proxy level** (Caddy auto-sets it; Nginx needs explicit config). Do NOT set in the app when running on localhost/dev — it would break HTTP access.

### Example Nginx config:
```nginx
add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
```

### Example Caddy:
Caddy sets HSTS automatically when serving over HTTPS.

## Where Headers Are Set

**File:** `app.py` — `security_headers_middleware` (middleware)

All security headers are set in a single middleware function that runs on every response.

## Assessment

**GOOD** — All critical headers present except HSTS (which belongs at the reverse proxy level). CSP is reasonably strict given the use of inline scripts/styles from Jinja2 templates.
