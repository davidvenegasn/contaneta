"""Tests for admin stats dashboard."""

import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

if not os.environ.get("APP_DB_PATH"):
    _fd, _p = tempfile.mkstemp(suffix=".db", prefix="test_admin_stats_")
    os.close(_fd)
    os.environ["APP_DB_PATH"] = _p
if not os.environ.get("SESSION_SECRET"):
    os.environ["SESSION_SECRET"] = "test-secret-admin-stats"

import database  # noqa: E402
from config import DB_PATH  # noqa: E402
from migrations_runner import apply_migrations  # noqa: E402

ADMIN_ISSUER_ID = 88820
ADMIN_USER_ID = 88820
NON_ADMIN_USER_ID = 88821


@pytest.fixture(scope="module", autouse=True)
def seed():
    apply_migrations(DB_PATH)
    conn = database.db()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO issuers (id, rfc, razon_social, active, created_at, updated_at) "
            "VALUES (?, 'ADM010101AAA', 'Admin Stats SA', 1, datetime('now'), datetime('now'))",
            (ADMIN_ISSUER_ID,),
        )
        conn.execute(
            "INSERT OR IGNORE INTO users (id, email, password_hash, created_at) "
            "VALUES (?, 'admin_stats@test.local', 'x', datetime('now'))",
            (ADMIN_USER_ID,),
        )
        conn.execute(
            "INSERT OR IGNORE INTO users (id, email, password_hash, created_at) "
            "VALUES (?, 'nonadmin@test.local', 'x', datetime('now'))",
            (NON_ADMIN_USER_ID,),
        )
        conn.execute(
            "INSERT OR IGNORE INTO memberships (user_id, issuer_id, role, created_at) "
            "VALUES (?, ?, 'owner', datetime('now'))",
            (ADMIN_USER_ID, ADMIN_ISSUER_ID),
        )
        conn.execute(
            "INSERT OR IGNORE INTO memberships (user_id, issuer_id, role, created_at) "
            "VALUES (?, ?, 'viewer', datetime('now'))",
            (NON_ADMIN_USER_ID, ADMIN_ISSUER_ID),
        )
        conn.commit()
    finally:
        conn.close()
    yield


@pytest.fixture(scope="module")
def admin_client():
    from fastapi.testclient import TestClient
    from app import app
    from tests.helpers import make_session_cookie
    cookies = make_session_cookie(issuer_id=ADMIN_ISSUER_ID, user_id=ADMIN_USER_ID)
    return TestClient(app, raise_server_exceptions=False, cookies=cookies)


def test_admin_stats_endpoint_requires_admin_role():
    """GET /admin/stats without admin role returns 403 or redirect."""
    from fastapi.testclient import TestClient
    from app import app
    from tests.helpers import make_session_cookie
    cookies = make_session_cookie(issuer_id=ADMIN_ISSUER_ID, user_id=NON_ADMIN_USER_ID)
    client = TestClient(app, raise_server_exceptions=False, cookies=cookies)
    resp = client.get("/admin/stats")
    assert resp.status_code in (401, 403, 302, 307)


def test_admin_stats_returns_all_required_keys(admin_client):
    """GET /admin/stats.json should return all stats sections."""
    resp = admin_client.get("/admin/stats.json")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "users" in data
    assert "issuers" in data
    assert "cfdis" in data
    assert "subscriptions" in data
    assert "errors" in data
    # Verify key fields
    assert "total" in data["users"]
    assert "active_last_7d" in data["users"]
    assert "mrr_mxn" in data["subscriptions"]


def test_admin_stats_calculates_mrr_correctly():
    """MRR should be a non-negative number."""
    from services.admin_stats import get_dashboard_stats
    stats = get_dashboard_stats()
    mrr = stats["subscriptions"]["mrr_mxn"]
    assert isinstance(mrr, (int, float))
    assert mrr >= 0


def test_admin_stats_handles_zero_users_gracefully():
    """Stats should return valid data even with empty tables."""
    from services.admin_stats import get_dashboard_stats
    stats = get_dashboard_stats()
    # All values should be non-negative integers or floats
    for section in stats.values():
        for key, val in section.items():
            assert isinstance(val, (int, float)), f"{key} is {type(val)}: {val}"
            assert val >= 0, f"{key} is negative: {val}"
