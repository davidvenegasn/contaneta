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

## Workflow (Research → Plan → Implement → Review → QA)

For new features or non-trivial tasks, follow this sequence strictly. A task is non-trivial if it involves:
- multiple files/layers
- API changes
- data model changes (migrations)
- external integrations (SAT, Stripe, Facturapi, Banxico)
- async/stateful logic
- user-facing behavior changes

For trivial fixes (typo, single-line CSS), this flow is optional.

### Global constraints

1. **One step per message** — In a single assistant message, execute ONLY ONE of: Research, Planner, Programmer, Reviewer, QA. Stop after that step.
2. **No implicit transitions** — Do NOT start the next step unless the user explicitly asks (e.g., "pasa al planner", "implementa", "haz el review").
3. **No cross-step output** — While in Research, do NOT output code or plan. While in Planner, do NOT output code. While in Programmer, do NOT redesign. While in Reviewer, do NOT implement fixes.
4. **Saved artifact gate** — Do NOT proceed to the next step unless the artifact for the current step has been saved to disk in `context/{phase}/{YYYY-MM-DD}-{slug}.md`.

### Stop conditions per phase

- **Research**: After saving research doc or asking questions, STOP.
- **Planner**: After saving plan, STOP.
- **Programmer**: After implementing + saving log, STOP.
- **Reviewer**: After saving review, STOP.
- **QA**: After saving QA report, STOP.

Skills for each phase live in `.claude/skills/`.

## Naming conventions (Python)

### Files
- Use **lowercase with underscores**: `bank_statements.py`, `sat_credentials.py`
- Test files: `test_<module>.py` (pytest convention)
- Template files: lowercase with underscores: `portal_facturas.html`
- Migration files: `NNN_<descriptive_name>.sql`

### Code
- **Classes**: PascalCase — `InvoiceService`, `BankStatement`
- **Functions/methods/variables**: snake_case — `get_invoice_by_id`, `current_user`
- **Constants**: UPPER_SNAKE_CASE — `MAX_FIEL_SIZE`, `SESSION_TIMEOUT`
- **Private**: leading underscore — `_internal_helper()`
- **Module-level "magic"**: dunder — `__all__`, `__init__`

### Booleans
Prefix with `is_`, `has_`, `can_`, `should_`:
- `is_authenticated`, `has_active_subscription`, `can_edit_invoice`

### Collections
Use plural nouns:
- `users`, `invoices`, `bank_movements`

### Routes (URL paths)
- Lowercase with hyphens: `/portal/bank-movements`, `/api/invoice-templates`
- Resource-then-action pattern: `/api/invoices/:id/cancel`, NOT `/api/cancel-invoice/:id`
- Use HTTP verbs to indicate action when possible (GET/POST/PATCH/DELETE)

### Avoid
- Generic names: `data`, `item`, `thing`, `process`, `handle`
- Single-letter variables (except loop counters)
- Abbreviations unless universally understood

## File size limits

- **No source file should exceed 350 lines.**
- If a file approaches the limit, split it into smaller modules grouped in a subfolder with an `__init__.py` acting as aggregator.
- Current known violations (pending refactor): `routers/portal/bank.py` (~1850 lines), `routers/api/invoices.py` (~2000 lines). Address opportunistically when working in those areas.

Exception: migration files, generated files, vendor code.

## Import validation

Before generating or modifying code that uses imports:

1. **Verify the imported module/function exists** in the current codebase.
2. **Verify the signature matches** what you intend to call (param count, types).
3. **Verify the import path** follows the project structure.
4. **Do NOT invent symbols** — if you need a helper that does not exist, either:
   - Implement it explicitly (logged in the plan), OR
   - Stop and report it as missing.

Example mistake to avoid: referencing `ALLOWED_CER`, `ALLOWED_KEY`, `MAX_FIEL_SIZE` after a refactor when those constants were not moved to the new file.

## Documentation rules

### Docstrings
- All public functions and classes have docstrings (PEP 257).
- Use Google or NumPy style. Be consistent within a module.
- Document params, returns, raises.

Example:
```python
def get_month_totals(issuer_id: int, ym: str, direction: str) -> dict:
    """Compute monthly totals (subtotal, IVA, retenciones) from CFDI.

    Args:
        issuer_id: Tenant ID.
        ym: Year-month in YYYY-MM format (or YYYY for annual view).
        direction: 'issued' or 'received'.

    Returns:
        Dict with keys: total_base, total_iva, total_retenciones, total_iva_neto.

    Raises:
        ValueError: If ym is malformed.
    """
```

### Inline comments
- English.
- Explain WHY, not WHAT (the code already says what).
- Reserve for non-obvious decisions, edge cases, workarounds.

### Module docstrings
- One-line summary at the top of each module.

### Service docs
- Each service module's `__init__.py` should explain what the service does and its public API.

## Testing rules

### Framework
- pytest (not unittest).
- Tests in `tests/` directory.
- Naming: `test_<module>.py`, functions `test_<scenario>()`.

### Coverage
- Target 90% coverage in changed code.
- Use `pytest --cov` when relevant.

### Structure
- Each test must include both success AND error scenarios.
- Use `tests/helpers.py:make_session_cookie` for auth in integration tests.
- Use `pytest.fixture` for setup/teardown.
- Use real SQLite (not mocks) when feasible — the testing DB is fast.

### What NOT to mock
- Do not mock functions from the same module being tested.
- Do not mock the database; use real SQLite test fixtures.
- DO mock external services (Facturapi, Banxico, Stripe webhooks).

### Test naming pattern
`should_<expected_behavior>_when_<condition>`:
- `test_should_return_404_when_invoice_not_found`
- `test_should_compute_iva_neto_when_retenciones_present`

## Architecture (strict layer order)

```
HTTP Request
     │
     ▼
routers/{module}/{feature}.py   ← validates input, calls services
     │
     ▼
services/{domain}/*.py            ← business logic, stateless functions
     │
     ▼
database.py (db, db_rows, db_execute)  ← raw parameterized SQL
     │
     ▼
SQLite (invoicing.db) + catalogs (catalogs.db)
```

### Layer rules
- **Routers** validate input + auth + tenancy, call services, format response. NO business logic. NO direct DB.
- **Services** are stateless functions (not classes unless needed). One service per domain (`services/bank/`, `services/sat/`, `services/invoices/`, `services/billing/`, `services/auth/`).
- **Database helpers** in `database.py` — raw SQL with `?` placeholders. NEVER f-strings for queries.
- Cross-layer calls only DOWN: router → service → database. Never sideways or upward.

### Multi-tenancy (CRITICAL)
- Every data query MUST filter by `issuer_id`.
- Use `Depends(get_portal_issuer)` for portal routes and `Depends(get_admin_user)` for admin.
- Tenant ID comes from the session cookie, NOT from request body/query.

### Error handling
- Use FastAPI's `HTTPException(status_code, detail)` for HTTP errors.
- Use custom exceptions inheriting from `AppError` for business errors.
- Log significant events with `logging.getLogger(__name__)`.

## No silent improvisation

When implementing changes:

- **No coding before rules**: read this `CLAUDE.md` and any active plan in `context/plan/`.
- **No silent assumptions**: if user/research/plan doesn't state something, ask or log as blocker.
- **No scope creep**: do not "clean up" unrelated code. Do not rename or reorganize beyond what was asked.
- **No improvisation**: do not redesign during implementation. Material deviations require a plan update.

If you find an obvious bug in unrelated code, report it but do NOT fix it in the same change.
