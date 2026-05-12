"""E2E tests for critical user flows using Playwright.

Run: .venv/bin/pytest tests/e2e/ -v
Requires: server running at localhost:8000, playwright chromium installed.

These tests use a signed session cookie to bypass login (see conftest.py).
"""
import pytest

pytestmark = pytest.mark.e2e


def test_landing_loads(page):
    """GET / should return 200 and have a visible title."""
    resp = page.goto("/")
    assert resp.status == 200
    assert page.title()


def test_login_page_renders(page):
    """Login page should have email and password fields."""
    page.goto("/login")
    assert page.locator("input[name='email'], input[name='identifier']").count() > 0


def test_portal_home_accessible(page):
    """Authenticated user should see the portal home."""
    resp = page.goto("/portal/home")
    assert resp.status == 200
    # Should not be a redirect to login (check we're on portal)
    assert "/login" not in page.url


def test_facturas_list_renders(page):
    """Navigate to /portal/facturas — table OR empty state should be visible, never skeleton."""
    page.goto("/portal/facturas?tab=issued")
    page.wait_for_load_state("networkidle")
    # Wait for JS to finish
    page.wait_for_timeout(2000)

    table_body = page.locator("#tableBody")
    empty_state = page.locator("#emptyState")

    # Either we have rows or empty state — but NOT skeleton loaders stuck
    has_rows = table_body.locator("tr").count() > 0
    empty_visible = empty_state.is_visible() if empty_state.count() > 0 else False

    if has_rows:
        # Verify rows don't contain skeleton classes
        first_row_html = table_body.locator("tr").first.inner_html()
        assert "skeleton" not in first_row_html, "Table still showing skeleton loaders"
    else:
        assert empty_visible, "No rows and empty state not visible — possible JS error"


def test_facturas_no_console_errors(page):
    """No JavaScript errors on facturas page."""
    errors = []
    page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)
    page.goto("/portal/facturas?tab=issued")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(1000)

    # Filter out known non-critical errors
    critical = [e for e in errors if "favicon" not in e.lower()]
    assert len(critical) == 0, f"Console errors: {critical}"


def test_bank_movements_page_loads(page):
    """/portal/bank/movements should load without errors."""
    resp = page.goto("/portal/bank/movements")
    assert resp.status == 200
    assert "/login" not in page.url


def test_clientes_page_loads(page):
    """/portal/catalogos?tab=clientes should be accessible."""
    resp = page.goto("/portal/catalogos?tab=clientes")
    assert resp.status == 200


def test_productos_page_loads(page):
    """/portal/catalogos?tab=productos should be accessible."""
    resp = page.goto("/portal/catalogos?tab=productos")
    assert resp.status == 200


def test_api_catalogs_return_200(page):
    """Catalog API endpoints should return 200 (regression for split bug)."""
    endpoints = [
        "/api/catalogs/moneda",
        "/api/catalogs/uso_cfdi",
        "/api/catalogs/forma_pago",
        "/api/catalogs/regimen_fiscal",
    ]
    for ep in endpoints:
        resp = page.goto(ep)
        assert resp.status == 200, f"{ep} returned {resp.status}"
