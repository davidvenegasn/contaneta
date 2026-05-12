"""Smoke tests: verify public routes return 200 and gated routes require auth."""
import pytest
from starlette.testclient import TestClient

from app import app

client = TestClient(app, raise_server_exceptions=False)


# ---------- Public routes (should return 200 without auth) ----------

@pytest.mark.parametrize("path", [
    "/health",
    "/ready",
    "/login",
    "/signup",
    "/pricing",
    "/robots.txt",
    "/sitemap.xml",
])
def test_public_route_ok(path):
    r = client.get(path)
    assert r.status_code in (200, 204), f"{path} returned {r.status_code}"


@pytest.mark.parametrize("path", [
    "/demo",
    "/seguridad",
    "/terms",
    "/privacy",
])
def test_public_page_ok(path):
    r = client.get(path, follow_redirects=False)
    # Some may redirect (302) or render (200)
    assert r.status_code in (200, 301, 302), f"{path} returned {r.status_code}"


# ---------- Gated routes (should redirect or 401 without auth) ----------

@pytest.mark.parametrize("path", [
    "/portal/home",
    "/portal/facturas",
    "/portal/catalogos",
    "/portal/movimientos",
    "/portal/month-close",
    "/portal/config/sat",
])
def test_portal_route_requires_auth(path):
    r = client.get(path, follow_redirects=False)
    # Portal HTML routes redirect to /login when not authenticated
    assert r.status_code in (302, 303, 307, 401), f"{path} returned {r.status_code} (expected redirect to login)"


@pytest.mark.parametrize("path", [
    "/api/invoices/issued?ym=2026-01",
    "/api/invoices/received?ym=2026-01",
    "/api/customers",
    "/api/products",
    "/api/account/status",
    "/api/search?q=test",
])
def test_api_route_requires_auth(path):
    r = client.get(path)
    assert r.status_code in (401, 403, 422), f"{path} returned {r.status_code} (expected 401/403)"
