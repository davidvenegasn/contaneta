"""Tests for account deletion request (LFPDPPP compliance)."""
import secrets

import pytest
from starlette.testclient import TestClient

from app import app
from database import db, db_rows, has_column, table_exists
from tests.helpers import make_session_cookie


@pytest.fixture()
def client():
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture()
def test_user():
    """Create a test user + issuer for deletion tests."""
    from services.auth.users import create_user, add_membership, hash_password
    unique_email = f"deltest_{secrets.token_hex(4)}@example.com"
    conn = db()
    try:
        cur = conn.execute(
            "INSERT INTO issuers (rfc, razon_social, active, created_at, updated_at) VALUES (?, ?, 1, datetime('now'), datetime('now'))",
            ("DEL0101010AA", "Deletion Test SA"),
        )
        issuer_id = cur.lastrowid
        conn.commit()
    finally:
        conn.close()
    pw_hash = hash_password("TestPass123!")
    user_result = create_user(email=unique_email, password_hash=pw_hash)
    user_id = user_result["id"] if isinstance(user_result, dict) else user_result
    add_membership(user_id, issuer_id, "owner")
    cookie = make_session_cookie(issuer_id, user_id)

    yield {"user_id": user_id, "issuer_id": issuer_id, "cookie": cookie}

    # Cleanup
    conn = db()
    try:
        conn.execute("DELETE FROM account_deletion_requests WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM memberships WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.execute("DELETE FROM issuers WHERE id = ?", (issuer_id,))
        conn.commit()
    finally:
        conn.close()


class TestDeleteAccountRequest:
    """Verify account deletion request flow."""

    def test_should_create_pending_request(self, client, test_user):
        """POST /portal/settings/delete-account with 'ELIMINAR' creates request."""
        from services.auth.csrf import generate_csrf_token
        token = generate_csrf_token()
        r = client.post(
            "/portal/settings/delete-account",
            data={"csrf_token": token, "confirm_text": "ELIMINAR"},
            cookies=test_user["cookie"],
            follow_redirects=False,
        )
        assert r.status_code == 302
        assert "deletion_requested" in r.headers.get("location", "")
        # Verify DB
        rows = db_rows(
            "SELECT status, scheduled_for FROM account_deletion_requests WHERE user_id = ?",
            (test_user["user_id"],),
        )
        assert len(rows) == 1
        assert rows[0]["status"] == "pending"
        if has_column(db(), "account_deletion_requests", "scheduled_for"):
            assert rows[0]["scheduled_for"] is not None

    def test_should_reject_without_confirm_text(self, client, test_user):
        """POST without typing 'ELIMINAR' should redirect with error."""
        from services.auth.csrf import generate_csrf_token
        token = generate_csrf_token()
        r = client.post(
            "/portal/settings/delete-account",
            data={"csrf_token": token, "confirm_text": "wrong"},
            cookies=test_user["cookie"],
            follow_redirects=False,
        )
        assert r.status_code == 302
        assert "ELIMINAR" in r.headers.get("location", "")
        # No request should be created
        rows = db_rows(
            "SELECT id FROM account_deletion_requests WHERE user_id = ?",
            (test_user["user_id"],),
        )
        assert len(rows) == 0

    def test_should_reject_duplicate_request(self, client, test_user):
        """Second request when one is already pending should error."""
        from services.auth.csrf import generate_csrf_token
        # First request
        token1 = generate_csrf_token()
        client.post(
            "/portal/settings/delete-account",
            data={"csrf_token": token1, "confirm_text": "ELIMINAR"},
            cookies=test_user["cookie"],
            follow_redirects=False,
        )
        # Second request (need fresh cookie since first logs out)
        token2 = generate_csrf_token()
        r = client.post(
            "/portal/settings/delete-account",
            data={"csrf_token": token2, "confirm_text": "ELIMINAR"},
            cookies=test_user["cookie"],
            follow_redirects=False,
        )
        assert r.status_code == 302
        assert "pendiente" in r.headers.get("location", "").lower() or "Ya+existe" in r.headers.get("location", "")


class TestCancelDeletion:
    """Verify cancellation of pending deletion."""

    def test_should_cancel_pending_request(self, client, test_user):
        """Cancel deletion should mark request as rejected."""
        from services.auth.csrf import generate_csrf_token
        # Create pending request
        conn = db()
        try:
            conn.execute(
                "INSERT INTO account_deletion_requests (user_id, status, requested_at, scheduled_for) VALUES (?, 'pending', datetime('now'), datetime('now', '+30 days'))",
                (test_user["user_id"],),
            )
            conn.commit()
        finally:
            conn.close()
        # Cancel it
        token = generate_csrf_token()
        r = client.post(
            "/portal/settings/cancel-deletion",
            data={"csrf_token": token},
            cookies=test_user["cookie"],
            follow_redirects=False,
        )
        assert r.status_code == 302
        assert "cancelada" in r.headers.get("location", "").lower()
        # Verify status changed
        rows = db_rows(
            "SELECT status FROM account_deletion_requests WHERE user_id = ?",
            (test_user["user_id"],),
        )
        assert all(r["status"] == "rejected" for r in rows)
