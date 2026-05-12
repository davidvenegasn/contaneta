"""Tests for the user settings page (/portal/settings)."""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_test_db = os.environ.get("APP_DB_PATH")
if not _test_db:
    _fd, _test_db = tempfile.mkstemp(suffix=".db", prefix="test_settings_")
    os.close(_fd)
    os.environ["APP_DB_PATH"] = _test_db
if not os.environ.get("SESSION_SECRET"):
    os.environ["SESSION_SECRET"] = "test-secret-settings"

import pytest  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

from app import app  # noqa: E402
from config import DB_PATH  # noqa: E402
from database import db  # noqa: E402
from migrations_runner import apply_migrations  # noqa: E402
from services.auth import csrf as csrf_service  # noqa: E402
from services.auth import users as users_service  # noqa: E402
from tests.helpers import make_session_cookie  # noqa: E402

ISSUER_ID = 8800
USER_ID = 8800
USER_EMAIL = "settings-test@test.local"
USER_PASSWORD = "OldPass123!"


@pytest.fixture(scope="module")
def setup_data():
    """Create a test issuer, user with known password, and membership."""
    apply_migrations(DB_PATH)
    pw_hash = users_service.hash_password(USER_PASSWORD)
    conn = db()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO issuers (id, rfc, razon_social, regimen_fiscal, active, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, 1, datetime('now'), datetime('now'))",
            (ISSUER_ID, "XAXX010101000", "Test Settings SA", "626"),
        )
        conn.execute(
            "INSERT OR IGNORE INTO users (id, email, name, password_hash, created_at) "
            "VALUES (?, ?, ?, ?, datetime('now'))",
            (USER_ID, USER_EMAIL, "Test User", pw_hash),
        )
        # Always reset password to known state (in case a prior test run changed it)
        conn.execute(
            "UPDATE users SET password_hash = ?, session_nonce = NULL WHERE id = ?",
            (pw_hash, USER_ID),
        )
        conn.execute(
            "INSERT OR IGNORE INTO memberships (user_id, issuer_id, role, created_at) "
            "VALUES (?, ?, 'owner', datetime('now'))",
            (USER_ID, ISSUER_ID),
        )
        conn.commit()
    finally:
        conn.close()
    cookies = make_session_cookie(issuer_id=ISSUER_ID, user_id=USER_ID)
    return cookies


class TestSettingsPageRender:
    """GET /portal/settings renders correctly."""

    def test_should_return_200_for_authenticated_user(self, setup_data):
        cookies = setup_data
        client = TestClient(app, raise_server_exceptions=False, cookies=cookies)
        r = client.get("/portal/settings")
        assert r.status_code == 200

    def test_should_contain_profile_section(self, setup_data):
        cookies = setup_data
        client = TestClient(app, raise_server_exceptions=False, cookies=cookies)
        r = client.get("/portal/settings")
        assert r.status_code == 200
        assert "Perfil de usuario" in r.text

    def test_should_contain_password_section(self, setup_data):
        cookies = setup_data
        client = TestClient(app, raise_server_exceptions=False, cookies=cookies)
        r = client.get("/portal/settings")
        assert r.status_code == 200
        assert "Cambiar contraseña" in r.text

    def test_should_contain_fiscal_section(self, setup_data):
        cookies = setup_data
        client = TestClient(app, raise_server_exceptions=False, cookies=cookies)
        r = client.get("/portal/settings")
        assert r.status_code == 200
        assert "Datos fiscales" in r.text

    def test_should_show_user_email_prefilled(self, setup_data):
        cookies = setup_data
        client = TestClient(app, raise_server_exceptions=False, cookies=cookies)
        r = client.get("/portal/settings")
        assert r.status_code == 200
        assert USER_EMAIL in r.text


class TestProfileUpdate:
    """POST /portal/settings/profile updates user name and email."""

    def test_should_update_profile_and_redirect(self, setup_data):
        cookies = setup_data
        client = TestClient(app, raise_server_exceptions=False, cookies=cookies)
        csrf = csrf_service.generate_csrf_token()
        r = client.post(
            "/portal/settings/profile",
            data={"csrf_token": csrf, "name": "Updated Name", "email": USER_EMAIL},
            follow_redirects=False,
        )
        assert r.status_code == 302
        assert "success" in r.headers.get("location", "").lower()
        # Verify the name was actually updated
        user = users_service.get_user_by_id(USER_ID)
        assert user["name"] == "Updated Name"

    def test_should_fail_without_csrf(self, setup_data):
        cookies = setup_data
        client = TestClient(app, raise_server_exceptions=False, cookies=cookies)
        r = client.post(
            "/portal/settings/profile",
            data={"csrf_token": "", "name": "Hacker", "email": "hack@test.local"},
            follow_redirects=False,
        )
        assert r.status_code == 403


class TestPasswordChange:
    """POST /portal/settings/password changes password correctly."""

    def test_should_fail_with_wrong_current_password(self, setup_data):
        cookies = setup_data
        client = TestClient(app, raise_server_exceptions=False, cookies=cookies)
        csrf = csrf_service.generate_csrf_token()
        r = client.post(
            "/portal/settings/password",
            data={
                "csrf_token": csrf,
                "current_password": "WrongPassword999",
                "new_password": "NewPass456!",
                "confirm_password": "NewPass456!",
            },
            follow_redirects=False,
        )
        assert r.status_code == 302
        location = r.headers.get("location", "")
        assert "incorrecta" in location or "error" in location.lower()

    def test_should_fail_when_passwords_do_not_match(self, setup_data):
        cookies = setup_data
        client = TestClient(app, raise_server_exceptions=False, cookies=cookies)
        csrf = csrf_service.generate_csrf_token()
        r = client.post(
            "/portal/settings/password",
            data={
                "csrf_token": csrf,
                "current_password": USER_PASSWORD,
                "new_password": "NewPass456!",
                "confirm_password": "DifferentPass!",
            },
            follow_redirects=False,
        )
        assert r.status_code == 302
        location = r.headers.get("location", "")
        assert "coinciden" in location or "error" in location.lower()

    def test_should_succeed_with_correct_current_password(self, setup_data):
        cookies = setup_data
        client = TestClient(app, raise_server_exceptions=False, cookies=cookies)
        csrf = csrf_service.generate_csrf_token()
        r = client.post(
            "/portal/settings/password",
            data={
                "csrf_token": csrf,
                "current_password": USER_PASSWORD,
                "new_password": "NewPass456!",
                "confirm_password": "NewPass456!",
            },
            follow_redirects=False,
        )
        assert r.status_code == 302
        location = r.headers.get("location", "")
        assert "success" in location.lower()
        # Verify the password was actually changed
        new_hash = users_service.get_user_password_hash(USER_ID)
        assert users_service.verify_password("NewPass456!", new_hash)
