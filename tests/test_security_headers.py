"""Regression tests for HTTP security headers."""
from starlette.testclient import TestClient

from app import app

client = TestClient(app, raise_server_exceptions=False)


def _get_headers():
    r = client.get("/health")
    return r.headers


def test_x_content_type_options():
    assert _get_headers().get("x-content-type-options") == "nosniff"


def test_x_frame_options():
    assert _get_headers().get("x-frame-options") == "DENY"


def test_referrer_policy():
    assert _get_headers().get("referrer-policy") == "strict-origin-when-cross-origin"


def test_permissions_policy():
    pp = _get_headers().get("permissions-policy", "")
    assert "geolocation=()" in pp
    assert "camera=()" in pp


def test_content_security_policy():
    csp = _get_headers().get("content-security-policy", "")
    assert "default-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp
    assert "object-src 'none'" in csp


def test_x_request_id_present():
    assert _get_headers().get("x-request-id") is not None
