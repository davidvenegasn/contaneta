"""Tests for the public landing page and pricing SPEI section."""

import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

if not os.environ.get("APP_DB_PATH"):
    _fd, _p = tempfile.mkstemp(suffix=".db", prefix="test_landing_")
    os.close(_fd)
    os.environ["APP_DB_PATH"] = _p
if not os.environ.get("SESSION_SECRET"):
    os.environ["SESSION_SECRET"] = "test-secret-landing"

import database  # noqa: E402
from config import DB_PATH  # noqa: E402
from migrations_runner import apply_migrations  # noqa: E402


@pytest.fixture(scope="module", autouse=True)
def setup_db():
    apply_migrations(DB_PATH)
    yield


@pytest.fixture(scope="module")
def anon_client():
    from fastapi.testclient import TestClient
    from app import app
    return TestClient(app, raise_server_exceptions=False)


def test_root_shows_landing_for_anonymous(anon_client):
    """GET / without session should render the landing page."""
    resp = anon_client.get("/", follow_redirects=False)
    assert resp.status_code == 200
    assert "contaneta" in resp.text.lower()
    assert "prueba gratis" in resp.text.lower()


def test_root_shows_landing_for_authenticated_with_portal_cta(anon_client):
    """GET / with a session cookie should still show landing, but with 'Ir al portal' CTA."""
    from tests.helpers import make_session_cookie
    cookies = make_session_cookie(issuer_id=1, user_id=1)
    resp = anon_client.get("/", follow_redirects=False, cookies=cookies)
    assert resp.status_code == 200
    assert "Ir al portal" in resp.text


def test_landing_includes_plan_prices(anon_client):
    """Landing page should display the 3 plan prices."""
    resp = anon_client.get("/")
    # New landing: Básico $119, Acompañado $499, Personalizado $1,299
    assert "$119" in resp.text
    assert "$499" in resp.text
    assert "$1,299" in resp.text


def test_landing_has_nav_links(anon_client):
    """Landing page should have navigation links to login and register."""
    resp = anon_client.get("/")
    assert "/login" in resp.text
    assert "/register" in resp.text
    # In-page anchors for sections
    assert "#precios" in resp.text
    assert "#funciones" in resp.text


def test_pricing_has_spei_section(anon_client):
    """Pricing page should include SPEI payment instructions."""
    resp = anon_client.get("/pricing")
    assert resp.status_code == 200
    assert "SPEI" in resp.text
    assert "CLABE" in resp.text
    assert "transferencia" in resp.text.lower()
