"""Tests for trusted proxy X-Forwarded-For handling (Phase 2 -- Security MEDIUM)."""
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_test_db = os.environ.get("APP_DB_PATH")
if not _test_db:
    _fd, _test_db = tempfile.mkstemp(suffix=".db", prefix="test_proxy_")
    os.close(_fd)
    os.environ["APP_DB_PATH"] = _test_db
if not os.environ.get("SESSION_SECRET"):
    os.environ["SESSION_SECRET"] = "test-secret-proxy"


from services.auth.rate_limit import get_client_ip, _is_trusted_proxy


def _fake_request(client_host: str, headers: dict | None = None):
    """Build a minimal mock Request for testing get_client_ip."""
    req = MagicMock()
    req.client = MagicMock()
    req.client.host = client_host
    req.headers = headers or {}
    return req


class TestIsTrustedProxy:
    def test_localhost_is_trusted(self):
        assert _is_trusted_proxy("127.0.0.1") is True

    def test_ipv6_localhost_is_trusted(self):
        assert _is_trusted_proxy("::1") is True

    def test_private_10_range_trusted(self):
        assert _is_trusted_proxy("10.0.0.1") is True
        assert _is_trusted_proxy("10.255.255.255") is True

    def test_private_172_range_trusted(self):
        assert _is_trusted_proxy("172.16.0.1") is True
        assert _is_trusted_proxy("172.31.255.255") is True

    def test_private_192_range_trusted(self):
        assert _is_trusted_proxy("192.168.1.1") is True

    def test_public_ip_not_trusted(self):
        assert _is_trusted_proxy("8.8.8.8") is False
        assert _is_trusted_proxy("203.0.113.1") is False

    def test_unknown_not_trusted(self):
        assert _is_trusted_proxy("unknown") is False
        assert _is_trusted_proxy("") is False


class TestGetClientIp:
    def test_direct_connection_no_proxy_headers(self):
        """Without X-Forwarded-For, use direct client IP."""
        req = _fake_request("203.0.113.50")
        assert get_client_ip(req) == "203.0.113.50"

    def test_trusted_proxy_uses_forwarded_for(self):
        """When request comes from trusted proxy (127.0.0.1), trust X-Forwarded-For."""
        req = _fake_request("127.0.0.1", {"x-forwarded-for": "203.0.113.50"})
        assert get_client_ip(req) == "203.0.113.50"

    def test_untrusted_source_ignores_forwarded_for(self):
        """When request comes from untrusted IP, ignore X-Forwarded-For (anti-spoofing)."""
        req = _fake_request("8.8.8.8", {"x-forwarded-for": "1.2.3.4"})
        # Should return the direct client IP, NOT the spoofed header
        assert get_client_ip(req) == "8.8.8.8"

    def test_trusted_proxy_with_chain(self):
        """X-Forwarded-For may contain a chain; use the first (leftmost) entry."""
        req = _fake_request("10.0.0.5", {"x-forwarded-for": "203.0.113.50, 10.0.0.1"})
        assert get_client_ip(req) == "203.0.113.50"

    def test_trusted_proxy_uses_x_real_ip(self):
        """When request comes from trusted proxy, X-Real-IP is also trusted."""
        req = _fake_request("192.168.1.1", {"x-real-ip": "203.0.113.99"})
        assert get_client_ip(req) == "203.0.113.99"

    def test_no_client_returns_unknown(self):
        """Edge case: no client at all."""
        req = MagicMock()
        req.client = None
        req.headers = {}
        assert get_client_ip(req) == "unknown"
