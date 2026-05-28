"""Tests for plan_usage badge in quick-invoice bootstrap API."""
import secrets
from unittest.mock import patch

import pytest
from starlette.testclient import TestClient

from app import app
from database import db
from tests.helpers import make_session_cookie


@pytest.fixture()
def client():
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture()
def test_issuer():
    """Create a minimal issuer + user for bootstrap API testing."""
    conn = db()
    try:
        cur = conn.execute(
            "INSERT INTO issuers (rfc, razon_social, active, created_at, updated_at) VALUES (?, ?, 1, datetime('now'), datetime('now'))",
            (f"PLAN{secrets.token_hex(3)}AA", "Plan Usage Test SA"),
        )
        issuer_id = cur.lastrowid
        conn.commit()
    finally:
        conn.close()

    from services.auth.users import create_user, add_membership, hash_password

    email = f"plantest_{secrets.token_hex(4)}@example.com"
    pw_hash = hash_password("TestPass123!")
    user_result = create_user(email=email, password_hash=pw_hash)
    user_id = user_result["id"] if isinstance(user_result, dict) else user_result
    add_membership(user_id, issuer_id, "owner")
    cookie = make_session_cookie(issuer_id, user_id)

    yield {"issuer_id": issuer_id, "user_id": user_id, "cookie": cookie}

    conn = db()
    try:
        conn.execute("DELETE FROM plan_usage WHERE issuer_id = ?", (issuer_id,))
        conn.execute("DELETE FROM memberships WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.execute("DELETE FROM issuers WHERE id = ?", (issuer_id,))
        conn.commit()
    finally:
        conn.close()


class TestBootstrapPlanUsage:
    """Verify plan_usage is returned in quick-invoice bootstrap."""

    def test_bootstrap_returns_plan_usage_when_available(self, client, test_issuer):
        """Bootstrap should include plan_usage dict when billing module works."""
        mock_usage = {"usage": 3, "limit": 10, "plan": "starter", "allowed": True}
        with patch("services.billing.plans.check_limit", return_value=mock_usage):
            r = client.get("/api/quick-invoice/bootstrap", cookies=test_issuer["cookie"])
        assert r.status_code == 200
        data = r.json()["data"]
        assert "plan_usage" in data
        pu = data["plan_usage"]
        assert pu["current"] == 3
        assert pu["limit"] == 10
        assert pu["plan"] == "starter"
        assert pu["allowed"] is True

    def test_bootstrap_returns_plan_usage_when_limit_reached(self, client, test_issuer):
        """Bootstrap should flag allowed=false when plan limit reached."""
        mock_usage = {"usage": 10, "limit": 10, "plan": "free", "allowed": False}
        with patch("services.billing.plans.check_limit", return_value=mock_usage):
            r = client.get("/api/quick-invoice/bootstrap", cookies=test_issuer["cookie"])
        assert r.status_code == 200
        data = r.json()["data"]
        pu = data["plan_usage"]
        assert pu["current"] == 10
        assert pu["allowed"] is False

    def test_bootstrap_returns_null_plan_usage_on_billing_error(self, client, test_issuer):
        """Bootstrap should return plan_usage=null if billing module fails."""
        with patch("services.billing.plans.check_limit", side_effect=Exception("billing down")):
            r = client.get("/api/quick-invoice/bootstrap", cookies=test_issuer["cookie"])
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["plan_usage"] is None
