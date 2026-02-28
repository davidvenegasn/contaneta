# Security Notes — ContaNeta

## Threat Model

### What we protect

| Asset | Threat | Mitigation |
|-------|--------|------------|
| **Session cookies** | Theft, forgery | HMAC-SHA256 signed, HttpOnly, Secure, SameSite=Lax, 24h TTL |
| **CSRF tokens** | Cross-site request forgery | HMAC tokens with 1h TTL on all POST forms |
| **FIEL credentials** (.cer/.key) | Exposure at rest | AES-GCM encrypted via `crypto_at_rest`, per-issuer derived keys (HKDF) |
| **Bank account CLABE** | Exposure in DB | Encrypted at rest (AES-GCM); UI shows only last 4 digits |
| **Redirect targets** (`next` params) | Open redirect to external sites | `safe_next_url()` validates relative paths, whitelisted prefixes |
| **Token login** (URL `?token=`) | Brute force enumeration | Rate limited (5/min per IP), tokens never logged |
| **User passwords** | Breach | bcrypt hashed, never stored in plain text |
| **.env / secrets** | Accidental commit or deploy | `.gitignore`, `safe_export.sh` with post-zip verification |
| **SQL injection** | Data exfiltration | Parameterized queries (`?` placeholders) everywhere, no f-string SQL |
| **XSS** | Script injection | CSP header, Jinja2 auto-escaping, `X-Content-Type-Options: nosniff` |

### Security headers (set in `app.py` middleware)

- `Content-Security-Policy`: `default-src 'self'; frame-ancestors 'none'; ...`
- `X-Frame-Options`: `DENY`
- `X-Content-Type-Options`: `nosniff`
- `Referrer-Policy`: `strict-origin-when-cross-origin`
- `Permissions-Policy`: geolocation, microphone, camera, payment, usb, serial all disabled

## Pre-production Checklist

- [ ] `SESSION_SECRET` set in `.env` (random hex, min 32 chars)
- [ ] `ENV=prod` set (enforces strict config validation)
- [ ] `SITE_URL` set to actual domain (for redirects, billing callbacks)
- [ ] `.env` is NOT in the deploy package — verify with `safe_export.sh`
- [ ] `storage/` directory exists and is writable but NOT publicly served
- [ ] HTTPS enforced (Caddy auto-TLS or nginx + certbot)
- [ ] `COOKIE_SECURE=1` (default in prod)
- [ ] Database file (`invoicing.db`) is NOT world-readable (chmod 600)
- [ ] Backups encrypted or stored in access-controlled location
- [ ] `DEV_MODE=0` (default in prod) — disables demo access and verbose logging
- [ ] Stripe webhook secret configured if billing is active
- [ ] Rate limiting active on login, signup, forgot-password, token login
- [ ] Log files rotated (see `deploy/logrotate-conta.example`)

## What must NEVER go in a deploy zip

```
.env                    # All secrets
storage/                # Uploaded files, FIEL certs, XML/PDF
storage/credentials/    # Encrypted FIEL private keys
backup/                 # Database and storage backups
invoicing.db*           # Application database with user data
keys/                   # Signing/encryption keys
.venv/                  # Python environment
__pycache__/            # Bytecode
*.log                   # Server logs
tests/                  # Test suite
```

Use `bash scripts/safe_export.sh` to generate a verified-clean deploy package.

## Encryption at Rest

- **Module**: `services/crypto_at_rest.py`
- **Algorithm**: AES-256-GCM with 12-byte random nonce
- **Key derivation**: HKDF-SHA256 from master key, per-issuer salt (`issuer:{id}`)
- **Master key**: `AT_REST_MASTER_KEY` env var (base64url or hex), falls back to SHA-256 of `SESSION_SECRET`
- **Used for**: FIEL .cer/.key files, bank account CLABE numbers
- **Format**: `enc:v1:<nonce_b64>.<ciphertext_b64>` (text) or `CNENC1<nonce><ct>` (binary)

## Rate Limiting

- **Module**: `services/rate_limit.py`
- **Type**: In-memory sliding window per IP
- **Defaults**: 10 attempts / 60 seconds
- **Applied to**: login, signup, forgot-password, reset-password, FIEL upload/validate, SAT sync, token login (5/60s)
