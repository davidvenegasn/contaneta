"""Tests for the in-app notification system (service + API endpoints)."""
import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_test_db = os.environ.get("APP_DB_PATH")
if not _test_db:
    _fd, _test_db = tempfile.mkstemp(suffix=".db", prefix="test_notif_")
    os.close(_fd)
    os.environ["APP_DB_PATH"] = _test_db
if not os.environ.get("SESSION_SECRET"):
    os.environ["SESSION_SECRET"] = "test-secret-notif"

from fastapi.testclient import TestClient  # noqa: E402

from app import app  # noqa: E402
from config import DB_PATH  # noqa: E402
from database import db  # noqa: E402
from migrations_runner import apply_migrations  # noqa: E402
from services import notifications as notif_svc  # noqa: E402
from services.auth import csrf as csrf_service  # noqa: E402
from tests.helpers import make_session_cookie  # noqa: E402

ISSUER_ID = 9001
USER_ID = 9001


@pytest.fixture(autouse=True)
def _setup_db():
    """Apply migrations and seed minimal tenant data before each test."""
    apply_migrations(DB_PATH)
    conn = db()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO issuers (id, rfc, razon_social, active, created_at, updated_at) "
            "VALUES (?, 'NOTIFTEST01', 'Notif Test Co', 1, datetime('now'), datetime('now'))",
            (ISSUER_ID,),
        )
        conn.execute(
            "INSERT OR IGNORE INTO users (id, email, password_hash, created_at) "
            "VALUES (?, 'notif@test.local', '$2b$12$x', datetime('now'))",
            (USER_ID,),
        )
        conn.execute(
            "INSERT OR IGNORE INTO memberships (user_id, issuer_id, role, created_at) "
            "VALUES (?, ?, 'owner', datetime('now'))",
            (USER_ID, ISSUER_ID),
        )
        # Clean notifications from previous test runs
        conn.execute("DELETE FROM notifications WHERE issuer_id = ?", (ISSUER_ID,))
        conn.commit()
    finally:
        conn.close()
    yield


# ─── Service-level tests ──────────────────────────────────────────────────────


class TestCreateNotification:
    def test_should_create_notification_and_return_id(self):
        nid = notif_svc.create_notification(ISSUER_ID, "Test title", "Test body")
        assert nid is not None
        assert isinstance(nid, int)
        assert nid > 0

    def test_should_return_none_when_title_empty(self):
        nid = notif_svc.create_notification(ISSUER_ID, "", "body only")
        assert nid is None

    def test_should_set_defaults_correctly(self):
        nid = notif_svc.create_notification(ISSUER_ID, "Default test")
        items = notif_svc.get_notifications(ISSUER_ID, limit=1, unread_only=True)
        assert len(items) >= 1
        found = [n for n in items if n["id"] == nid]
        assert len(found) == 1
        n = found[0]
        assert n["severity"] == "info"
        assert n["read_at"] is None

    def test_should_accept_all_parameters(self):
        nid = notif_svc.create_notification(
            ISSUER_ID,
            "Warning notice",
            message="Something needs attention",
            type="warning",
            link="/portal/home",
            user_id=USER_ID,
        )
        assert nid is not None


class TestGetNotifications:
    def test_should_return_empty_list_when_none_exist(self):
        result = notif_svc.get_notifications(ISSUER_ID)
        assert result == []

    def test_should_return_notifications_newest_first(self):
        notif_svc.create_notification(ISSUER_ID, "First")
        notif_svc.create_notification(ISSUER_ID, "Second")
        result = notif_svc.get_notifications(ISSUER_ID)
        assert len(result) == 2
        assert result[0]["title"] == "Second"
        assert result[1]["title"] == "First"

    def test_should_filter_unread_only(self):
        nid1 = notif_svc.create_notification(ISSUER_ID, "Will be read")
        notif_svc.create_notification(ISSUER_ID, "Still unread")
        notif_svc.mark_read(ISSUER_ID, nid1)
        unread = notif_svc.get_notifications(ISSUER_ID, unread_only=True)
        assert len(unread) == 1
        assert unread[0]["title"] == "Still unread"
        all_notifs = notif_svc.get_notifications(ISSUER_ID, unread_only=False)
        assert len(all_notifs) == 2

    def test_should_respect_limit(self):
        for i in range(5):
            notif_svc.create_notification(ISSUER_ID, f"Notif {i}")
        result = notif_svc.get_notifications(ISSUER_ID, limit=3)
        assert len(result) == 3


class TestMarkRead:
    def test_should_mark_notification_as_read(self):
        nid = notif_svc.create_notification(ISSUER_ID, "To read")
        assert notif_svc.mark_read(ISSUER_ID, nid) is True
        items = notif_svc.get_notifications(ISSUER_ID, unread_only=False)
        found = [n for n in items if n["id"] == nid]
        assert found[0]["read_at"] is not None

    def test_should_return_false_when_already_read(self):
        nid = notif_svc.create_notification(ISSUER_ID, "Already read")
        notif_svc.mark_read(ISSUER_ID, nid)
        # Second call returns False because it's already read
        assert notif_svc.mark_read(ISSUER_ID, nid) is False

    def test_should_return_false_for_nonexistent_id(self):
        assert notif_svc.mark_read(ISSUER_ID, 999999) is False

    def test_should_enforce_tenant_isolation(self):
        """Notification from issuer A cannot be marked read by issuer B."""
        nid = notif_svc.create_notification(ISSUER_ID, "Tenant A only")
        other_issuer = ISSUER_ID + 1
        assert notif_svc.mark_read(other_issuer, nid) is False


class TestMarkAllRead:
    def test_should_mark_all_unread_as_read(self):
        notif_svc.create_notification(ISSUER_ID, "One")
        notif_svc.create_notification(ISSUER_ID, "Two")
        notif_svc.create_notification(ISSUER_ID, "Three")
        count = notif_svc.mark_all_read(ISSUER_ID)
        assert count == 3
        assert notif_svc.count_unread(ISSUER_ID) == 0

    def test_should_return_zero_when_none_unread(self):
        count = notif_svc.mark_all_read(ISSUER_ID)
        assert count == 0


class TestCountUnread:
    def test_should_return_zero_when_empty(self):
        assert notif_svc.count_unread(ISSUER_ID) == 0

    def test_should_count_only_unread(self):
        nid1 = notif_svc.create_notification(ISSUER_ID, "Unread 1")
        notif_svc.create_notification(ISSUER_ID, "Unread 2")
        assert notif_svc.count_unread(ISSUER_ID) == 2
        notif_svc.mark_read(ISSUER_ID, nid1)
        assert notif_svc.count_unread(ISSUER_ID) == 1

    def test_should_not_count_other_tenants(self):
        notif_svc.create_notification(ISSUER_ID, "Mine")
        other = ISSUER_ID + 1
        assert notif_svc.count_unread(other) == 0


# ─── API endpoint tests ───────────────────────────────────────────────────────


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def cookies():
    return make_session_cookie(ISSUER_ID, USER_ID)


@pytest.fixture
def csrf_token():
    return csrf_service.generate_csrf_token()


class TestNotificationsListAPI:
    def test_should_return_notifications_list(self, client, cookies):
        notif_svc.create_notification(ISSUER_ID, "API test")
        r = client.get("/api/notifications?limit=10", cookies=cookies)
        assert r.status_code == 200
        j = r.json()
        assert j["ok"] is True
        assert isinstance(j["items"], list)
        assert len(j["items"]) >= 1
        # Should include unread_count in meta
        assert "meta" in j
        assert "unread_count" in j["meta"]

    def test_should_filter_unread_only(self, client, cookies):
        nid = notif_svc.create_notification(ISSUER_ID, "Read one")
        notif_svc.create_notification(ISSUER_ID, "Unread one")
        notif_svc.mark_read(ISSUER_ID, nid)
        r = client.get("/api/notifications?unread_only=true", cookies=cookies)
        assert r.status_code == 200
        items = r.json()["items"]
        for item in items:
            assert item["read_at"] is None

    def test_should_return_401_without_auth(self, client):
        r = client.get("/api/notifications")
        assert r.status_code in (401, 403, 302)


class TestNotificationsUnreadCountAPI:
    def test_should_return_unread_count(self, client, cookies):
        notif_svc.create_notification(ISSUER_ID, "Count me")
        r = client.get("/api/notifications/unread-count", cookies=cookies)
        assert r.status_code == 200
        j = r.json()
        assert j["ok"] is True
        assert j["data"]["unread_count"] >= 1


class TestMarkReadAPI:
    def test_should_mark_single_as_read(self, client, cookies, csrf_token):
        nid = notif_svc.create_notification(ISSUER_ID, "Mark me")
        r = client.post(
            f"/api/notifications/{nid}/read",
            cookies=cookies,
            headers={"X-CSRF-Token": csrf_token},
        )
        assert r.status_code == 200
        assert r.json()["ok"] is True
        assert r.json()["data"]["marked"] is True

    def test_should_return_false_for_nonexistent(self, client, cookies, csrf_token):
        r = client.post(
            "/api/notifications/999999/read",
            cookies=cookies,
            headers={"X-CSRF-Token": csrf_token},
        )
        assert r.status_code == 200
        assert r.json()["data"]["marked"] is False

    def test_should_require_csrf(self, client, cookies):
        nid = notif_svc.create_notification(ISSUER_ID, "CSRF test")
        r = client.post(f"/api/notifications/{nid}/read", cookies=cookies)
        assert r.status_code == 403


class TestReadAllAPI:
    def test_should_mark_all_as_read(self, client, cookies, csrf_token):
        notif_svc.create_notification(ISSUER_ID, "Batch 1")
        notif_svc.create_notification(ISSUER_ID, "Batch 2")
        r = client.post(
            "/api/notifications/read-all",
            cookies=cookies,
            headers={"X-CSRF-Token": csrf_token},
        )
        assert r.status_code == 200
        j = r.json()
        assert j["ok"] is True
        assert j["data"]["marked"] >= 2
        assert notif_svc.count_unread(ISSUER_ID) == 0

    def test_legacy_mark_all_read_endpoint_works(self, client, cookies, csrf_token):
        """The old /notifications/mark-all-read path should still work."""
        notif_svc.create_notification(ISSUER_ID, "Legacy test")
        r = client.post(
            "/api/notifications/mark-all-read",
            cookies=cookies,
            headers={"X-CSRF-Token": csrf_token},
        )
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_should_require_csrf(self, client, cookies):
        r = client.post("/api/notifications/read-all", cookies=cookies)
        assert r.status_code == 403
