# ContaNeta

Multi-tenant invoicing platform for Mexican tax compliance (CFDI/SAT). Server-rendered portal with FastAPI, SQLite, and Jinja2.

## Stack

- **Backend:** Python 3.11+, FastAPI, SQLite (WAL mode), Gunicorn
- **Frontend:** Jinja2 templates, vanilla JS/CSS (no build step)
- **Billing:** Stripe (subscriptions + webhooks)
- **SAT integration:** PHP scripts via subprocess (FIEL validation, CFDI XML sync)

## Quick Start

```bash
# 1. Clone and enter the project
git clone <repo-url> && cd conta_invoicing_mvp_PRO_clean

# 2. Run the setup script (creates venv, installs deps)
bash scripts/setup_dev.sh

# 3. Copy and configure environment
cp .env.example .env
# Edit .env — defaults work for local dev

# 4. Start the server (auto-applies DB migrations on startup)
./run_server.sh

# 5. Create a demo user (first time only)
python scripts/ensure_demo_user.py
# Then open http://127.0.0.1:8000/login?token=demo
```

The server runs at `http://127.0.0.1:8000`. The portal is at `/portal/home`.

## Tests

```bash
.venv/bin/pytest -q                              # All tests (17 currently)
.venv/bin/pytest tests/test_health.py -v          # Single file
.venv/bin/pytest tests/test_health.py::test_name  # Single test
```

## Project Structure

```
app.py                  # FastAPI app, middleware, startup
routers/
  portal.py             # Portal HTML routes (/portal/*)
  api.py                # JSON API routes (/api/*)
  billing.py            # Stripe webhooks and billing
  deps.py               # Shared dependencies (auth, tenant resolution)
services/               # Business logic (stateless functions)
database.py             # SQLite connection factory, helpers
templates/              # Jinja2 templates (Spanish UI)
static/                 # CSS, JS, images (no bundler)
migrations/             # Numbered SQL files (auto-applied on startup)
sat_sync/               # PHP scripts for SAT/CFDI integration
tests/                  # Pytest suite
scripts/                # Dev/ops utilities
```

## Key Documentation

- [CLAUDE.md](CLAUDE.md) — Architecture, conventions, and dev guidelines
- [DEPLOY_GUIDE.md](DEPLOY_GUIDE.md) — Production deployment
- [docs/ops/OPERATIONS.md](docs/ops/OPERATIONS.md) — Operations runbook
- [docs/guides/](docs/guides/) — Admin, auth, billing, and SAT guides
- [MIGRATIONS.md](MIGRATIONS.md) — Database migration system

## Development workflow with Claude

This project follows a strict workflow when using AI assistance for non-trivial changes:
**Research → Plan → Implement → Review → QA**

- Skills live in `.claude/skills/`
- Artifacts saved to `context/`
- Rules enforced in `CLAUDE.md`

For trivial changes (typo, one-line fix), skip the workflow.

See `.claude/skills/README.md` for details.
