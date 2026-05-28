"""Tests for FIEL expiry badge rendering in settings and home pages."""
import secrets
from unittest.mock import patch

import pytest
from starlette.testclient import TestClient

from app import app
from database import db, db_rows
from tests.helpers import make_session_cookie


@pytest.fixture()
def client():
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture()
def test_issuer_with_fiel():
    """Create an issuer with sat_credentials for FIEL expiry testing."""
    conn = db()
    try:
        cur = conn.execute(
            "INSERT INTO issuers (rfc, razon_social, active, created_at, updated_at) VALUES (?, ?, 1, datetime('now'), datetime('now'))",
            (f"FIEL{secrets.token_hex(3)}AA", "FIEL Expiry Test SA"),
        )
        issuer_id = cur.lastrowid
        conn.execute(
            "INSERT INTO sat_credentials (issuer_id, fiel_cer_path, fiel_key_path, fiel_key_password, validation_ok, created_at, updated_at) "
            "VALUES (?, 'fake.cer', 'fake.key', 'pass', 1, datetime('now'), datetime('now'))",
            (issuer_id,),
        )
        conn.commit()
    finally:
        conn.close()

    from services.auth.users import create_user, add_membership, hash_password
    email = f"fieltest_{secrets.token_hex(4)}@example.com"
    pw_hash = hash_password("TestPass123!")
    user_result = create_user(email=email, password_hash=pw_hash)
    user_id = user_result["id"] if isinstance(user_result, dict) else user_result
    add_membership(user_id, issuer_id, "owner")
    cookie = make_session_cookie(issuer_id, user_id)

    yield {"issuer_id": issuer_id, "user_id": user_id, "cookie": cookie}

    conn = db()
    try:
        conn.execute("DELETE FROM sat_credentials WHERE issuer_id = ?", (issuer_id,))
        conn.execute("DELETE FROM memberships WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.execute("DELETE FROM issuers WHERE id = ?", (issuer_id,))
        conn.commit()
    finally:
        conn.close()


class TestFielExpiryBadgeSettings:
    """Verify FIEL expiry badge renders in settings page."""

    def test_settings_renders_fiel_expiry_badge(self, client, test_issuer_with_fiel):
        """Settings page should show FIEL expiry badge when credentials exist."""
        mock_fiel_data = {
            "rfc": "TEST010101AAA",
            "nombre": "Test SA",
            "expires_at": "2027-06-15T00:00:00+00:00",
            "days_until_expiry": 500,
        }
        with patch("services.sat.sat_credentials_secure.extract_fiel_subject", return_value=mock_fiel_data):
            r = client.get("/portal/settings", cookies=test_issuer_with_fiel["cookie"])
        assert r.status_code == 200
        html = r.text
        assert "2027-06-15" in html
        assert "500" in html
        assert "badge--success" in html

    def test_settings_renders_warning_badge_when_expiring_soon(self, client, test_issuer_with_fiel):
        """Settings page should show warning badge when FIEL expiring in 60 days."""
        mock_fiel_data = {
            "expires_at": "2026-07-28T00:00:00+00:00",
            "days_until_expiry": 60,
        }
        with patch("services.sat.sat_credentials_secure.extract_fiel_subject", return_value=mock_fiel_data):
            r = client.get("/portal/settings", cookies=test_issuer_with_fiel["cookie"])
        assert r.status_code == 200
        assert "badge--warn" in r.text
        assert "Expira pronto" in r.text

    def test_settings_renders_danger_badge_when_expired(self, client, test_issuer_with_fiel):
        """Settings page should show danger badge when FIEL is expired."""
        mock_fiel_data = {
            "expires_at": "2025-01-01T00:00:00+00:00",
            "days_until_expiry": -180,
        }
        with patch("services.sat.sat_credentials_secure.extract_fiel_subject", return_value=mock_fiel_data):
            r = client.get("/portal/settings", cookies=test_issuer_with_fiel["cookie"])
        assert r.status_code == 200
        assert "badge--danger" in r.text
        assert "EXPIRADA" in r.text


class TestFielExpiryBannerHome:
    """Verify FIEL expiry warning banner on home page."""

    def test_home_shows_warning_when_fiel_expires_soon(self, client, test_issuer_with_fiel):
        """Home page should show banner when FIEL expires in <= 30 days."""
        mock_fiel_data = {
            "expires_at": "2026-06-20T00:00:00+00:00",
            "days_until_expiry": 15,
        }
        with patch("services.sat.sat_credentials_secure.extract_fiel_subject", return_value=mock_fiel_data):
            r = client.get("/portal/home", cookies=test_issuer_with_fiel["cookie"])
        assert r.status_code == 200
        assert "expira en 15" in r.text.lower() or "15 d" in r.text

    def test_home_hides_banner_when_fiel_not_expiring(self, client, test_issuer_with_fiel):
        """Home page should NOT show banner when FIEL has > 30 days."""
        mock_fiel_data = {
            "expires_at": "2028-06-15T00:00:00+00:00",
            "days_until_expiry": 500,
        }
        with patch("services.sat.sat_credentials_secure.extract_fiel_subject", return_value=mock_fiel_data):
            r = client.get("/portal/home", cookies=test_issuer_with_fiel["cookie"])
        assert r.status_code == 200
        assert "EXPIRADA" not in r.text
        assert "expira en" not in r.text.lower()
