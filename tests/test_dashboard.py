"""Tests for the improved dashboard with actionable metrics."""
import os
import sys
import tempfile
from pathlib import Path

# Ensure test DB before importing app
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_test_db = os.environ.get("APP_DB_PATH")
if not _test_db:
    _fd, _test_db = tempfile.mkstemp(suffix=".db", prefix="test_dashboard_")
    os.close(_fd)
    os.environ["APP_DB_PATH"] = _test_db
if not os.environ.get("SESSION_SECRET"):
    os.environ["SESSION_SECRET"] = "test-secret-dashboard"

import pytest
from starlette.testclient import TestClient

from app import app  # noqa: E402
from config import DB_PATH  # noqa: E402
from database import db  # noqa: E402
from migrations_runner import apply_migrations  # noqa: E402
from tests.helpers import make_session_cookie  # noqa: E402


@pytest.fixture(scope="module")
def issuer_with_data():
    """Create a test issuer, user, and membership, returning (issuer_id, cookies)."""
    apply_migrations(DB_PATH)
    conn = db()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO issuers (id, rfc, razon_social, active, created_at, updated_at) "
            "VALUES (?, ?, ?, 1, datetime('now'), datetime('now'))",
            (9990, "XAXX010101000", "Test Dashboard SA"),
        )
        conn.execute(
            "INSERT OR IGNORE INTO users (id, email, password_hash, created_at) "
            "VALUES (?, 'dash@test.local', 'x', datetime('now'))",
            (9990,),
        )
        conn.execute(
            "INSERT OR IGNORE INTO memberships (user_id, issuer_id, role, created_at) "
            "VALUES (?, ?, 'owner', datetime('now'))",
            (9990, 9990),
        )
        conn.commit()
    finally:
        conn.close()

    cookies = make_session_cookie(issuer_id=9990, user_id=9990)
    return 9990, cookies


@pytest.fixture(scope="module")
def empty_issuer():
    """Create a test issuer with no data at all."""
    apply_migrations(DB_PATH)
    conn = db()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO issuers (id, rfc, razon_social, active, created_at, updated_at) "
            "VALUES (?, ?, ?, 1, datetime('now'), datetime('now'))",
            (9991, "XAXX010101001", "Test Empty SA"),
        )
        conn.execute(
            "INSERT OR IGNORE INTO users (id, email, password_hash, created_at) "
            "VALUES (?, 'empty@test.local', 'x', datetime('now'))",
            (9991,),
        )
        conn.execute(
            "INSERT OR IGNORE INTO memberships (user_id, issuer_id, role, created_at) "
            "VALUES (?, ?, 'owner', datetime('now'))",
            (9991, 9991),
        )
        conn.commit()
    finally:
        conn.close()

    cookies = make_session_cookie(issuer_id=9991, user_id=9991)
    return 9991, cookies


class TestDashboardEndpointOk:
    """Dashboard endpoint responds 200 with expected shape."""

    def test_should_return_200_for_authenticated_user(self, issuer_with_data):
        _, cookies = issuer_with_data
        client = TestClient(app, raise_server_exceptions=False, cookies=cookies)
        r = client.get("/portal/home")
        assert r.status_code == 200, f"Expected 200, got {r.status_code}"

    def test_should_contain_alerts_section_marker(self, issuer_with_data):
        _, cookies = issuer_with_data
        client = TestClient(app, raise_server_exceptions=False, cookies=cookies)
        r = client.get("/portal/home")
        assert r.status_code == 200
        body = r.text
        # Either alerts exist or all-clear message should appear (or neither if no data)
        has_alerts = "dashboard-alert-card" in body
        has_all_clear = "dashboard-all-clear" in body
        has_empty = "ui-empty" in body
        # At least one of these must be present in the page
        assert has_alerts or has_all_clear or has_empty, "Expected alert cards, all-clear message, or empty state"

    def test_should_contain_activity_feed(self, issuer_with_data):
        _, cookies = issuer_with_data
        client = TestClient(app, raise_server_exceptions=False, cookies=cookies)
        r = client.get("/portal/home")
        assert r.status_code == 200
        assert "activity-feed" in r.text or "Actividad reciente" in r.text

    def test_should_contain_trend_chart_container(self, issuer_with_data):
        _, cookies = issuer_with_data
        client = TestClient(app, raise_server_exceptions=False, cookies=cookies)
        r = client.get("/portal/home")
        assert r.status_code == 200
        assert "trendChartContainer" in r.text

    def test_should_reference_trend_chart(self, issuer_with_data):
        _, cookies = issuer_with_data
        client = TestClient(app, raise_server_exceptions=False, cookies=cookies)
        r = client.get("/portal/home")
        assert r.status_code == 200
        assert "months=6" in r.text or "Tendencia" in r.text

    def test_should_contain_quick_actions_section(self, issuer_with_data):
        _, cookies = issuer_with_data
        client = TestClient(app, raise_server_exceptions=False, cookies=cookies)
        r = client.get("/portal/home")
        assert r.status_code == 200
        assert "Acciones rapidas" in r.text or "actions-card__grid" in r.text


class TestDashboardEmptyIssuer:
    """Issuer without data: dashboard renders without errors."""

    def test_should_return_200_for_empty_issuer(self, empty_issuer):
        _, cookies = empty_issuer
        client = TestClient(app, raise_server_exceptions=False, cookies=cookies)
        r = client.get("/portal/home")
        assert r.status_code == 200, f"Expected 200 for empty issuer, got {r.status_code}"

    def test_should_render_without_errors_on_empty_data(self, empty_issuer):
        _, cookies = empty_issuer
        client = TestClient(app, raise_server_exceptions=False, cookies=cookies)
        r = client.get("/portal/home")
        assert r.status_code == 200
        # Page should not contain error messages
        assert "500" not in r.text[:500]
        assert "Internal Server Error" not in r.text

    def test_should_show_empty_state_or_next_actions_for_empty_issuer(self, empty_issuer):
        _, cookies = empty_issuer
        client = TestClient(app, raise_server_exceptions=False, cookies=cookies)
        r = client.get("/portal/home")
        assert r.status_code == 200
        # Either empty state or next-actions should be present
        has_empty = "ui-empty" in r.text
        has_actions = "next-actions-list" in r.text or "Siguiente paso" in r.text
        assert has_empty or has_actions


class TestMetricsTrendApi:
    """API /api/metrics/trend responds correctly."""

    def test_should_return_ok_with_data_array(self, issuer_with_data):
        _, cookies = issuer_with_data
        client = TestClient(app, raise_server_exceptions=False, cookies=cookies)
        r = client.get("/api/metrics/trend?months=12")
        assert r.status_code == 200
        j = r.json()
        assert j.get("ok") is True
        assert isinstance(j.get("data"), list)

    def test_should_accept_months_up_to_24(self, issuer_with_data):
        _, cookies = issuer_with_data
        client = TestClient(app, raise_server_exceptions=False, cookies=cookies)
        r = client.get("/api/metrics/trend?months=24")
        assert r.status_code == 200
        j = r.json()
        assert j.get("ok") is True

    def test_should_default_to_12_months(self, issuer_with_data):
        _, cookies = issuer_with_data
        client = TestClient(app, raise_server_exceptions=False, cookies=cookies)
        r = client.get("/api/metrics/trend")
        assert r.status_code == 200
        j = r.json()
        assert j.get("ok") is True
        data = j.get("data", [])
        # Should be at most 12 entries (or less if no data range)
        assert len(data) <= 12

    def test_should_return_ym_and_amounts_in_each_entry(self, issuer_with_data):
        _, cookies = issuer_with_data
        client = TestClient(app, raise_server_exceptions=False, cookies=cookies)
        r = client.get("/api/metrics/trend?months=3")
        assert r.status_code == 200
        j = r.json()
        for entry in j.get("data", []):
            assert "ym" in entry
            assert "ingresos" in entry
            assert "gastos" in entry


class TestDashboardServiceUnit:
    """Unit tests for services/dashboard.py functions."""

    def test_get_top_clients_returns_list(self, issuer_with_data):
        from services.dashboard import get_top_clients
        issuer_id, _ = issuer_with_data
        result = get_top_clients(issuer_id, limit=5)
        assert isinstance(result, list)

    def test_get_top_providers_returns_list(self, issuer_with_data):
        from services.dashboard import get_top_providers
        issuer_id, _ = issuer_with_data
        result = get_top_providers(issuer_id, limit=5)
        assert isinstance(result, list)

    def test_get_alerts_returns_list(self, issuer_with_data):
        from services.dashboard import get_alerts
        issuer_id, _ = issuer_with_data
        result = get_alerts(issuer_id, "2026-05")
        assert isinstance(result, list)

    def test_get_next_actions_returns_list_with_keys(self, issuer_with_data):
        from services.dashboard import get_next_actions
        issuer_id, _ = issuer_with_data
        result = get_next_actions(issuer_id, "2026-05")
        assert isinstance(result, list)
        assert len(result) >= 4
        for action in result:
            assert "key" in action
            assert "label" in action
            assert "done" in action
            assert "href" in action

    def test_get_alerts_empty_issuer(self, empty_issuer):
        from services.dashboard import get_alerts
        issuer_id, _ = empty_issuer
        result = get_alerts(issuer_id, "2026-05")
        assert isinstance(result, list)

    def test_get_next_actions_empty_issuer(self, empty_issuer):
        from services.dashboard import get_next_actions
        issuer_id, _ = empty_issuer
        result = get_next_actions(issuer_id, "2026-05")
        assert isinstance(result, list)
        assert len(result) >= 4
        for action in result:
            assert isinstance(action["done"], bool)

    def test_get_top_clients_empty_issuer(self, empty_issuer):
        from services.dashboard import get_top_clients
        issuer_id, _ = empty_issuer
        result = get_top_clients(issuer_id, limit=5)
        assert result == []

    def test_get_top_providers_empty_issuer(self, empty_issuer):
        from services.dashboard import get_top_providers
        issuer_id, _ = empty_issuer
        result = get_top_providers(issuer_id, limit=5)
        assert result == []
