# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

ContaNeta — a multi-tenant SaaS invoicing platform for Mexican tax compliance (CFDI/SAT). Built with FastAPI, SQLite (WAL mode), Jinja2 templates, and Stripe billing. SAT integration uses PHP scripts called via subprocess.

## Commands

```bash
# Setup
bash scripts/setup_dev.sh          # One-time dev environment setup
cp .env.example .env               # Then edit with your values

# Run server (auto-applies migrations on startup)
./run_server.sh                    # Or: python -m uvicorn app:app --reload --host 0.0.0.0 --port 8000

# Tests
.venv/bin/pytest -q                # Run all tests
.venv/bin/pytest tests/test_health.py -v   # Single test file
.venv/bin/pytest tests/test_health.py::test_name -v  # Single test

# Background worker
python worker.py --once            # Process one job
python worker.py --loop            # Continuous processing

# Smoke tests & health checks
bash scripts/check_all.sh

# Database reset (dev only)
bash scripts/reset_db.sh
```

## Architecture

### Request Flow

```
Client → Middleware (request_id → security_headers → redirect_token) → Router → Service → database.py → SQLite
```

### Layer Responsibilities

- **`app.py`** — FastAPI app, middleware registration, exception handlers, startup (migrations + config validation)
- **`routers/`** — HTTP handlers. All portal/API routes use `Depends(get_portal_issuer)` from `routers/deps.py` for auth + tenant resolution
- **`services/`** — Business logic. Stateless functions. Routers call services, services call `database.py`
- **`database.py`** — SQLite connection factory with WAL mode, dict row factory. Helpers: `db_rows()`, `db_execute()`, `transaction()`
- **`templates/`** — Jinja2 server-rendered HTML. No build step, no bundler. Base layouts: `base_portal.html` (classic), `base_portal_v2.html` (rail+drawer), `base_admin.html`
- **`config.py`** — All config from environment variables via `python-dotenv`. Strict validation in prod (`SESSION_SECRET` required, etc.)

### Multi-Tenancy Model

Tenant = Issuer (company/RFC). Every data query filters by `issuer_id`. The session cookie (HMAC-SHA256 signed) carries `user_id|issuer_id|expiry`. `get_portal_issuer()` in `routers/deps.py` resolves identity and sets `request.state.issuer_id`, `.user_id`, `.membership_role`. Roles: `owner`, `accountant`, `viewer`, `admin`.

### Database

Two SQLite databases:
- **`invoicing.db`** (path via `APP_DB_PATH`) — all application data
- **`catalogs/catalogs.db`** — read-only SAT catalogs (products, payment methods, tax regimes)

Migrations in `migrations/` as numbered SQL files (`001_*.sql`, `002_*.sql`, ...). Applied automatically on app startup by `migrations_runner.py`. Tracked in `schema_migrations` table.

### Authentication

Cookie-based sessions via `services/session.py`. Login sets HMAC-signed cookie. CSRF tokens (HMAC, 1h TTL) required on all POST forms via `services/csrf.py`. Rate limiting on login/registration via `services/rate_limit.py`. Admin impersonation uses 4-part cookie (`user_id|issuer_id|expiry|restore_issuer_id`).

### Job Queue

`services/jobs.py` implements a robust queue in the `jobs` table with dedupe (SHA-256 payload hash), lease-based locking, configurable retries, and exponential backoff. `worker.py` polls and processes jobs. Handler functions registered in `worker.py:_load_handlers()`.

### SAT Integration

PHP scripts in `sat_sync/` handle FIEL validation and CFDI XML sync with Mexico's SAT. Called from Python via `subprocess.run()` with timeouts. FIEL credentials stored encrypted at rest (AES-GCM) via `services/crypto_at_rest.py` and `services/sat_credentials_secure.py`.

### API Response Convention

API endpoints use `services/http.py` helpers: `ok(data)` and `ok_list(items, total)`. Error responses follow `{ ok: false, error: { code, message }, meta: { request_id } }`. Custom exceptions inherit from `AppError` (in services) with `code`, `public_message`, `status_code`.

## Key Conventions

- **No ORM** — raw parameterized SQL everywhere. Use `?` placeholders, never f-strings for queries.
- **All SQL migrations are idempotent** — use `IF NOT EXISTS`, `ADD COLUMN IF NOT EXISTS`, etc.
- **Services are stateless functions** — no classes. Import and call directly.
- **Templates use Spanish** for user-facing text (Mexican market). Code/comments in English.
- **Static assets served directly** — no webpack/vite. CSS in `static/css/`, JS in `static/js/`.
- **Stripe webhooks** in `routers/billing.py` handle subscription lifecycle events.
- **Audit trail** via `services/action_log.py` — log significant user actions with `log_action()`.
- **File downloads** are tenant-scoped and logged via `services/file_access_log.py`.

## Environment

Key variables (see `.env.example` for full list):
- `ENV` — `dev` or `prod`
- `DEV_MODE` — enables demo access and verbose logging (defaults to 1 in dev, 0 in prod)
- `SESSION_SECRET` — **required in prod**, random hex for cookie signing
- `APP_DB_PATH` — SQLite database path (default: `./invoicing.db`)
- `SITE_URL` — base URL for redirects and Stripe callbacks
- `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_PRICE_ID` — billing config

## Production Deployment

Gunicorn behind Caddy/Nginx. Systemd service in `deploy/conta-invoicing.service`. Backups via `scripts/backup_storage.sh`. SAT sync via cron (`sat_sync/cron_sat_sync.sh`).

## Refactor & Reorganization Rules

Safe moves only — no behavior changes during reorganization:

1. **Behavior must not change** — refactors are structural, not functional. If a response, query, or side-effect changes, it's not a refactor.
2. **URLs stay identical** — every route must respond at the same path before and after. No redirects, no renames.
3. **Tests before and after** — run `.venv/bin/pytest -q` before starting and after every move. Green → green or don't merge.
4. **Move, don't rewrite** — copy the code as-is first, then update imports. Resist the urge to "improve" while moving.
5. **Docs are archived, not deleted** — obsolete docs go to `_archive/`, never `rm`.
6. **Use `git mv`** — preserves blame history. Never `cp` + `rm`.
7. **One concern per commit** — each commit does exactly one thing: move a file, update imports, rename a symbol. Never mix.
8. **Verify imports after every move** — run `python -c "import app"` to confirm nothing broke. Do this after each file move, not just at the end.
