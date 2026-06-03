"""Tests for admin sync health dashboard."""

import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

if not os.environ.get("APP_DB_PATH"):
    _fd, _p = tempfile.mkstemp(suffix=".db", prefix="test_sync_health_")
    os.close(_fd)
    os.environ["APP_DB_PATH"] = _p
if not os.environ.get("SESSION_SECRET"):
    os.environ["SESSION_SECRET"] = "test-secret-sync-health"

import database  # noqa: E402
from config import DB_PATH  # noqa: E402
from migrations_runner import apply_migrations  # noqa: E402

ADMIN_ISSUER_ID = 90500
ADMIN_USER_ID = 90500
NON_ADMIN_USER_ID = 90501


@pytest.fixture(scope="module", autouse=True)
def seed():
    apply_migrations(DB_PATH)
    conn = database.db()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO issuers (id, rfc, razon_social, active, created_at, updated_at) "
            "VALUES (?, 'SYN010101AAA', 'Sync Health SA', 1, datetime('now'), datetime('now'))",
            (ADMIN_ISSUER_ID,),
        )
        conn.execute(
            "INSERT OR IGNORE INTO users (id, email, password_hash, created_at) "
            "VALUES (?, 'sync_health@test.local', 'x', datetime('now'))",
            (ADMIN_USER_ID,),
        )
        conn.execute(
            "INSERT OR IGNORE INTO users (id, email, password_hash, created_at) "
            "VALUES (?, 'nonadmin_sync@test.local', 'x', datetime('now'))",
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


def test_sync_health_requires_admin():
    """GET /admin/sync-health without admin role returns 403."""
    from fastapi.testclient import TestClient
    from app import app
    from tests.helpers import make_session_cookie
    cookies = make_session_cookie(issuer_id=ADMIN_ISSUER_ID, user_id=NON_ADMIN_USER_ID)
    client = TestClient(app, raise_server_exceptions=False, cookies=cookies)
    resp = client.get("/admin/sync-health")
    assert resp.status_code in (401, 403, 302, 307)


def test_sync_health_renders_for_admin(admin_client):
    """GET /admin/sync-health returns 200 with KPI cards."""
    resp = admin_client.get("/admin/sync-health")
    assert resp.status_code == 200
    assert "Sync Health" in resp.text
    assert "Issuers con FIEL" in resp.text
    assert "Tasa" in resp.text


def test_sync_health_shows_stats(admin_client):
    """Dashboard shows aggregate stats section."""
    resp = admin_client.get("/admin/sync-health")
    assert resp.status_code == 200
    # KPI labels should be present
    assert "En cola ahora" in resp.text
    assert "OK (24h)" in resp.text
    assert "Errores (24h)" in resp.text


def test_sync_health_shows_per_issuer_table(admin_client):
    """Dashboard shows per-issuer table headers."""
    resp = admin_client.get("/admin/sync-health")
    assert resp.status_code == 200
    assert "Estado por emisor" in resp.text
    assert "Emitidos OK" in resp.text
    assert "Recibidos OK" in resp.text


def test_sync_health_stats_functions():
    """Internal stats functions return valid data."""
    from routers.admin.sync_health import _sync_health_stats, _stale_issuers
    stats = _sync_health_stats()
    assert isinstance(stats["total_fiel_issuers"], int)
    assert isinstance(stats["queued_now"], int)
    assert isinstance(stats["ok_24h"], int)
    assert isinstance(stats["errors_24h"], int)
    assert stats["success_rate"] is None or isinstance(stats["success_rate"], float)

    stale = _stale_issuers()
    assert isinstance(stale, list)
