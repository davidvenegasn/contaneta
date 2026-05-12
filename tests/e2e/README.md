# E2E Tests — Playwright

Browser-based end-to-end tests for critical user flows.

## Prerequisites

```bash
.venv/bin/pip install playwright pytest-playwright
.venv/bin/playwright install chromium
```

## Run

```bash
# Start server first
./run_server.sh &

# Run E2E tests
.venv/bin/pytest tests/e2e/ -v

# Run with headed browser (debug)
.venv/bin/pytest tests/e2e/ -v --headed

# Run specific test
.venv/bin/pytest tests/e2e/test_critical_flows.py::test_facturas_list_renders -v
```

## Configuration

| Env Var | Default | Description |
|---------|---------|-------------|
| `E2E_BASE_URL` | `http://localhost:8000` | Server URL |
| `E2E_USER_ID` | `4` | Test user ID |
| `E2E_ISSUER_ID` | `4` | Test issuer ID |

## Notes

- Tests are marked with `@pytest.mark.e2e` — exclude from CI with `-m "not e2e"`
- A signed session cookie is injected automatically (no login flow needed)
- Server must be running before tests start
