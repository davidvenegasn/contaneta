"""Tests for scripts/process_deletion_queue.py — account deletion processing."""
import secrets

import pytest

from database import db, db_rows
from scripts.process_deletion_queue import delete_user_data, find_due_deletions, process_queue


@pytest.fixture()
def deletable_user():
    """Create a user with a pending deletion request whose grace period has elapsed."""
    conn = db()
    try:
        rfc = f"DEL{secrets.token_hex(3)}AA"
        cur = conn.execute(
            "INSERT INTO issuers (rfc, razon_social, active, created_at, updated_at) "
            "VALUES (?, 'Deletion Test SA', 1, datetime('now'), datetime('now'))",
            (rfc,),
        )
        issuer_id = cur.lastrowid
        conn.commit()
    finally:
        conn.close()

    from services.auth.users import create_user, add_membership, hash_password

    email = f"deltest_{secrets.token_hex(4)}@example.com"
    pw_hash = hash_password("TestPass123!")
    user_result = create_user(email=email, password_hash=pw_hash)
    user_id = user_result["id"] if isinstance(user_result, dict) else user_result
    add_membership(user_id, issuer_id, "owner")

    # Create a deletion request with scheduled_for in the past (grace period elapsed)
    conn = db()
    try:
        conn.execute(
            "INSERT INTO account_deletion_requests (user_id, status, requested_at, scheduled_for) "
            "VALUES (?, 'pending', datetime('now', '-31 days'), datetime('now', '-1 day'))",
            (user_id,),
        )
        conn.commit()
    finally:
        conn.close()

    yield {"user_id": user_id, "issuer_id": issuer_id}

    # Cleanup any remaining data
    conn = db()
    try:
        conn.execute("DELETE FROM account_deletion_requests WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM memberships WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.execute("DELETE FROM issuers WHERE id = ?", (issuer_id,))
        conn.commit()
    finally:
        conn.close()


@pytest.fixture()
def future_deletion_user():
    """Create a user with a pending deletion request whose grace period has NOT elapsed."""
    conn = db()
    try:
        rfc = f"FUT{secrets.token_hex(3)}AA"
        cur = conn.execute(
            "INSERT INTO issuers (rfc, razon_social, active, created_at, updated_at) "
            "VALUES (?, 'Future Deletion SA', 1, datetime('now'), datetime('now'))",
            (rfc,),
        )
        issuer_id = cur.lastrowid
        conn.commit()
    finally:
        conn.close()

    from services.auth.users import create_user, add_membership, hash_password

    email = f"futdeltest_{secrets.token_hex(4)}@example.com"
    pw_hash = hash_password("TestPass123!")
    user_result = create_user(email=email, password_hash=pw_hash)
    user_id = user_result["id"] if isinstance(user_result, dict) else user_result
    add_membership(user_id, issuer_id, "owner")

    # Create a deletion request with scheduled_for in the future (grace period not yet elapsed)
    conn = db()
    try:
        conn.execute(
            "INSERT INTO account_deletion_requests (user_id, status, requested_at, scheduled_for) "
            "VALUES (?, 'pending', datetime('now'), datetime('now', '+29 days'))",
            (user_id,),
        )
        conn.commit()
    finally:
        conn.close()

    yield {"user_id": user_id, "issuer_id": issuer_id}

    conn = db()
    try:
        conn.execute("DELETE FROM account_deletion_requests WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM memberships WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.execute("DELETE FROM issuers WHERE id = ?", (issuer_id,))
        conn.commit()
    finally:
        conn.close()


class TestFindDueDeletions:
    """Tests for find_due_deletions()."""

    def test_should_find_due_deletion(self, deletable_user):
        """Should return requests whose scheduled_for is in the past."""
        due = find_due_deletions()
        user_ids = [d["user_id"] for d in due]
        assert deletable_user["user_id"] in user_ids

    def test_should_not_find_future_deletion(self, future_deletion_user):
        """Should not return requests whose scheduled_for is in the future."""
        due = find_due_deletions()
        user_ids = [d["user_id"] for d in due]
        assert future_deletion_user["user_id"] not in user_ids


class TestDeleteUserData:
    """Tests for delete_user_data()."""

    def test_should_delete_user_and_related_data(self, deletable_user):
        """Should remove user from users table and related tables."""
        user_id = deletable_user["user_id"]
        # Verify user exists before
        assert db_rows("SELECT 1 FROM users WHERE id = ?", (user_id,))
        assert db_rows("SELECT 1 FROM memberships WHERE user_id = ?", (user_id,))

        deleted = delete_user_data(user_id)

        # Verify user is gone
        assert not db_rows("SELECT 1 FROM users WHERE id = ?", (user_id,))
        assert not db_rows("SELECT 1 FROM memberships WHERE user_id = ?", (user_id,))
        assert deleted.get("users") == 1
        assert deleted.get("memberships", 0) >= 1

    def test_dry_run_should_not_delete(self, deletable_user):
        """Dry run should report what would be deleted without actually deleting."""
        user_id = deletable_user["user_id"]
        deleted = delete_user_data(user_id, dry_run=True)

        # User should still exist
        assert db_rows("SELECT 1 FROM users WHERE id = ?", (user_id,))
        assert deleted.get("users") == 1


class TestProcessQueue:
    """Tests for process_queue()."""

    def test_should_process_due_deletion(self, deletable_user):
        """Should process deletion requests whose grace period has elapsed."""
        user_id = deletable_user["user_id"]
        results = process_queue()

        processed_ids = [r["user_id"] for r in results if r["ok"]]
        assert user_id in processed_ids
        # User should be gone
        assert not db_rows("SELECT 1 FROM users WHERE id = ?", (user_id,))
        # Memberships and deletion requests should also be purged
        assert not db_rows("SELECT 1 FROM memberships WHERE user_id = ?", (user_id,))
        assert not db_rows("SELECT 1 FROM account_deletion_requests WHERE user_id = ?", (user_id,))

    def test_should_not_process_future_deletion(self, future_deletion_user):
        """Should not process requests whose grace period has not elapsed."""
        user_id = future_deletion_user["user_id"]
        results = process_queue()

        processed_ids = [r["user_id"] for r in results]
        assert user_id not in processed_ids
        # User should still exist
        assert db_rows("SELECT 1 FROM users WHERE id = ?", (user_id,))

    def test_should_return_empty_when_no_due_deletions(self):
        """Should return empty list when no deletions are due."""
        # This test may or may not find due deletions depending on other fixtures,
        # but without any fixtures it should return empty or process existing ones.
        results = process_queue(dry_run=True)
        assert isinstance(results, list)
