# Production Environment Checklist

Verify all items before deploying to production. Admin can also check `/admin/config` for live status.

## Required Environment Variables

| Variable | Required | How to generate |
|----------|----------|-----------------|
| `ENV=prod` | **Yes** | Set to `prod` |
| `SESSION_SECRET` | **Yes** | `python3 -c "import secrets; print(secrets.token_hex(32))"` |
| `APP_DB_PATH` | **Yes** | Absolute path, e.g. `/var/lib/contaneta/invoicing.db` |
| `SITE_URL` | **Yes** (if Stripe) | e.g. `https://app.contaneta.com` |

## Strongly Recommended

| Variable | Why |
|----------|-----|
| `AT_REST_MASTER_KEY` | Dedicated encryption key (independent from SESSION_SECRET). Without it, changing SESSION_SECRET breaks all encrypted data |
| `COOKIE_SECURE=1` | Default in prod; requires HTTPS |
| `DEV_MODE=0` | Default in prod; disables demo access |

## Verify

```bash
# Quick check (on the server)
grep -c 'ENV=prod' /var/lib/contaneta/.env         # should print 1
grep -c 'SESSION_SECRET=' /var/lib/contaneta/.env   # should print 1
grep -c 'AT_REST_MASTER_KEY=' /var/lib/contaneta/.env  # should print 1

# Or visit /admin/config in the browser (admin-only)
```

## File Permissions

```bash
chmod 600 /var/lib/contaneta/.env
chmod 600 /var/lib/contaneta/invoicing.db
chmod 700 /var/lib/contaneta/storage/credentials/
```

## What Breaks Without These

| Missing | Impact |
|---------|--------|
| `SESSION_SECRET` | App refuses to start |
| `AT_REST_MASTER_KEY` | Falls back to SHA256(SESSION_SECRET) — works but rotating SESSION_SECRET invalidates all encrypted FIEL/CLABE data |
| `COOKIE_SECURE=0` in prod | Session cookies sent over HTTP (insecure) |
| `DEV_MODE=1` in prod | Demo access enabled, verbose error pages |
| `SITE_URL` missing | Stripe checkout callbacks fail, email links broken |
