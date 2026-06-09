"""Tests for htmx-powered SPA navigation in the portal."""

import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

if not os.environ.get("APP_DB_PATH"):
    _fd, _p = tempfile.mkstemp(suffix=".db", prefix="test_htmx_nav_")
    os.close(_fd)
    os.environ["APP_DB_PATH"] = _p
if not os.environ.get("SESSION_SECRET"):
    os.environ["SESSION_SECRET"] = "test-secret-htmx-nav"

import database  # noqa: E402
from config import DB_PATH  # noqa: E402
from migrations_runner import apply_migrations  # noqa: E402

ISSUER_ID = 91100
USER_ID = 91100


@pytest.fixture(scope="module", autouse=True)
def seed():
    apply_migrations(DB_PATH)
    conn = database.db()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO issuers (id, rfc, razon_social, active, created_at, updated_at) "
            "VALUES (?, 'HTX010101AAA', 'HTMX Nav SA', 1, datetime('now'), datetime('now'))",
            (ISSUER_ID,),
        )
        conn.execute(
            "INSERT OR IGNORE INTO users (id, email, password_hash, created_at) "
            "VALUES (?, 'htmx@test.local', 'x', datetime('now'))",
            (USER_ID,),
        )
        conn.execute(
            "INSERT OR IGNORE INTO memberships (user_id, issuer_id, role, created_at) "
            "VALUES (?, ?, 'owner', datetime('now'))",
            (USER_ID, ISSUER_ID),
        )
        conn.commit()
    finally:
        conn.close()
    yield


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient
    from app import app
    from tests.helpers import make_session_cookie
    cookies = make_session_cookie(issuer_id=ISSUER_ID, user_id=USER_ID)
    return TestClient(app, raise_server_exceptions=False, cookies=cookies)


def test_main_content_has_id(client):
    """Portal pages should have id='mainContent' for htmx swap target."""
    resp = client.get("/portal/home")
    assert resp.status_code == 200
    assert 'id="mainContent"' in resp.text


def test_hx_boost_enabled_on_body(client):
    """Body tag should have hx-boost='true' for SPA navigation."""
    resp = client.get("/portal/home")
    assert resp.status_code == 200
    assert 'hx-boost="true"' in resp.text


def test_htmx_script_loaded(client):
    """htmx library should be loaded in the page."""
    resp = client.get("/portal/home")
    assert resp.status_code == 200
    assert "htmx.org" in resp.text


def test_progress_bar_present(client):
    """Progress bar indicator should be present in HTML."""
    resp = client.get("/portal/home")
    assert resp.status_code == 200
    assert 'id="htmxProgressBar"' in resp.text


def test_csrf_token_present_in_forms(client):
    """Forms in portal pages should still have csrf_token hidden inputs."""
    resp = client.get("/portal/settings")
    assert resp.status_code == 200
    assert 'name="csrf_token"' in resp.text


def test_logout_form_has_boost_false(client):
    """Logout form should have hx-boost='false' to do full page nav."""
    resp = client.get("/portal/home")
    assert resp.status_code == 200
    assert 'action="/logout"' in resp.text
    # The logout form should have hx-boost="false"
    assert 'hx-boost="false"' in resp.text


def test_htmx_redirect_middleware_converts_302():
    """POST with HX-Request header should get HX-Redirect instead of 302."""
    from fastapi.testclient import TestClient
    from app import app
    from tests.helpers import make_session_cookie

    cookies = make_session_cookie(issuer_id=ISSUER_ID, user_id=USER_ID)
    client = TestClient(app, raise_server_exceptions=False, cookies=cookies)

    # Get CSRF token first
    resp = client.get("/portal/settings")
    # Extract csrf token from meta tag
    import re
    match = re.search(r'name="csrf-token"\s+content="([^"]+)"', resp.text)
    csrf_token = match.group(1) if match else ""

    # POST profile update with HX-Request header (simulating htmx boost)
    resp = client.post(
        "/portal/settings/profile",
        data={
            "razon_social": "Test SA",
            "regimen_fiscal": "616",
            "codigo_postal": "06600",
            "csrf_token": csrf_token,
        },
        headers={"HX-Request": "true"},
        follow_redirects=False,
    )
    # Should be 200 with HX-Redirect header instead of 302
    assert resp.status_code == 200
    assert "HX-Redirect" in resp.headers


def test_afterswap_script_present(client):
    """The htmx afterSwap handler script should be present."""
    resp = client.get("/portal/home")
    assert resp.status_code == 200
    assert "htmx:afterSwap" in resp.text
    assert "portal:pageReady" in resp.text
