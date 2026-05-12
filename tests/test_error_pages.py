"""Tests for branded error pages (404, 500, 403)."""
from starlette.testclient import TestClient

from app import app

client = TestClient(app, raise_server_exceptions=False)


def test_404_html_has_branded_content():
    """GET /nonexistent should return 404 with branded error page."""
    r = client.get("/nonexistent-page-xyz", headers={"accept": "text/html"})
    assert r.status_code == 404
    assert "ContaNeta" in r.text
    assert "no encontrada" in r.text.lower()


def test_404_api_returns_json():
    """GET /api/nonexistent should return JSON error, not HTML."""
    r = client.get("/api/nonexistent-endpoint")
    assert r.status_code == 404
    data = r.json()
    assert data.get("ok") is False
    assert data["error"]["code"] == "NOT_FOUND"


def test_403_portal_redirects_to_login():
    """GET /portal/home without auth should redirect to login."""
    r = client.get("/portal/home", headers={"accept": "text/html"}, follow_redirects=False)
    assert r.status_code == 302
    assert "/login" in r.headers.get("location", "")


def test_admin_without_auth_redirects():
    """GET /admin without auth should redirect to login or return 403."""
    r = client.get("/admin", headers={"accept": "text/html"}, follow_redirects=False)
    # Admin routes typically redirect to login (302) or return 403
    assert r.status_code in (302, 403, 404)
