# Contributing to ContaNeta

## Getting Started

```bash
git clone <repo-url> && cd conta_invoicing_mvp_PRO_clean
bash scripts/setup_dev.sh
cp .env.example .env  # Edit with your values
./run_server.sh
```

Visit http://localhost:8000/login. Run `python scripts/ensure_demo_user.py` for a test account.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                     Client (Browser)                     │
└──────────────────────────┬──────────────────────────────┘
                           │
                  ┌────────▼────────┐
                  │   Middleware     │
                  │ request_id      │
                  │ security_headers│
                  │ redirect_token  │
                  └────────┬────────┘
                           │
          ┌────────────────┼────────────────┐
          │                │                │
   ┌──────▼──────┐ ┌──────▼──────┐ ┌──────▼──────┐
   │ routers/    │ │ routers/    │ │ routers/    │
   │ public.py   │ │ portal/     │ │ api/        │
   │ auth.py     │ │ (8 modules) │ │ (8 modules) │
   │ billing.py  │ │ HTML+Jinja2 │ │ JSON API    │
   └──────┬──────┘ └──────┬──────┘ └──────┬──────┘
          │                │                │
          └────────────────┼────────────────┘
                           │
                  ┌────────▼────────┐
                  │   services/     │
                  │ auth/  billing/ │
                  │ sat/   invoices/│
                  │ jobs   schemas  │
                  └────────┬────────┘
                           │
                  ┌────────▼────────┐
                  │  database.py    │
                  │  SQLite (WAL)   │
                  └─────────────────┘
```

## Project Structure

```
app.py                 # FastAPI app, middleware, startup
config.py              # Env-based configuration
database.py            # SQLite connection factory
routers/
  api/                 # JSON API endpoints (8 modules)
  portal/              # HTML portal routes (8 modules)
  auth.py              # Login/signup/OAuth
  public.py            # Public pages, shared quotation links
  billing.py           # Stripe checkout + webhooks
  admin.py             # Admin panel
  deps.py              # Auth dependencies (get_portal_issuer)
services/
  auth/                # Session, CSRF, rate limiting
  sat/                 # SAT sync, crypto, credentials
  billing/             # Stripe subscription management
  invoices/            # Invoice engine, matching, exchange rates
templates/             # Jinja2 HTML templates (Spanish UI)
static/                # CSS, JS, images (no build step)
migrations/            # Numbered SQL files (auto-applied on startup)
```

## Development Workflow

1. **Branch from main**: `git checkout -b feature/your-feature`
2. **Write code**: Follow existing patterns (raw SQL, stateless services, no ORM)
3. **Test**: `pytest -q` (must pass before commit)
4. **Lint**: `ruff check .` (auto-fix with `ruff check --fix .`)
5. **Commit**: Clear, scoped messages (`feat:`, `fix:`, `refactor:`, `docs:`, `test:`)
6. **PR**: Include summary, test plan, and any migration notes

## Conventions

- **No ORM** — raw parameterized SQL with `?` placeholders everywhere
- **Services are stateless functions** — no classes, import and call directly
- **Templates in Spanish** — user-facing text for Mexican market
- **Migrations are idempotent** — use `IF NOT EXISTS`, `ADD COLUMN IF NOT EXISTS`
- **Static assets served directly** — no webpack/vite/bundler
- **All data queries filter by `issuer_id`** — multi-tenant isolation

## Testing

```bash
pytest -q                              # All tests
pytest tests/test_health.py -v         # Single file
pytest tests/test_health.py::test_name # Single test
```

Tests use `starlette.testclient.TestClient`. Session cookies are created with `make_session_cookie()` from `tests/conftest.py`.

## Database Migrations

Create `migrations/0XX_description.sql`. Use `IF NOT EXISTS` for idempotency. Migrations run automatically on app startup.

## Code Review Checklist

- [ ] All SQL uses parameterized queries (`?` placeholders)
- [ ] All data queries filter by `issuer_id` from session (not user input)
- [ ] CSRF token validated on all POST handlers
- [ ] Tests pass (`pytest -q`)
- [ ] Ruff clean (`ruff check .`)
- [ ] No secrets committed (`.env`, keys, credentials)
