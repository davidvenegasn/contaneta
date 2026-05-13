"""Tests for session invalidation on password change (Phase 3 -- Security MEDIUM)."""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Must create a fresh test DB before any imports that touch config/database
_fd, _test_db = tempfile.mkstemp(suffix=".db", prefix="test_pw_invalidate_")
os.close(_fd)
os.environ["APP_DB_PATH"] = _test_db
if not os.environ.get("SESSION_SECRET"):
    os.environ["SESSION_SECRET"] = "test-secret-pw-invalidation"

import pytest
from database import db, db_rows, has_column
from services.auth import session, users
from routers.deps import _session_invalidated_by_password_change


def _setup_test_db():
    """Create minimal schema for this test."""
    conn = db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS issuers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rfc TEXT,
            razon_social TEXT,
            active INTEGER NOT NULL DEFAULT 1,
            regimen_fiscal TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE,
            phone TEXT,
            name TEXT,
            password_hash TEXT,
            oauth_provider TEXT,
            oauth_id TEXT,
            active INTEGER DEFAULT 1,
            password_changed_at TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS memberships (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            issuer_id INTEGER NOT NULL,
            role TEXT NOT NULL DEFAULT 'owner',
            UNIQUE(user_id, issuer_id)
        )
    """)
    conn.commit()

    # Insert test issuer and user
    conn.execute(
        "INSERT OR IGNORE INTO issuers (id, rfc, razon_social) VALUES (1, 'TEST123456ABC', 'Test Co')"
    )
    pw_hash = users.hash_password("OldPassword123")
    conn.execute(
        "INSERT OR IGNORE INTO users (id, email, name, password_hash) VALUES (1, 'test@example.com', 'Test User', ?)",
        (pw_hash,),
    )
    conn.execute(
        "INSERT OR IGNORE INTO memberships (user_id, issuer_id, role) VALUES (1, 1, 'owner')"
    )
    conn.commit()
    conn.close()


_setup_test_db()


class TestPasswordChangedAtColumn:
    def test_column_exists(self):
        conn = db()
        try:
            assert has_column(conn, "users", "password_changed_at") is True
        finally:
            conn.close()


class TestUpdateUserPasswordSetsTimestamp:
    def test_password_change_updates_timestamp(self):
        """update_user_password must set password_changed_at."""
        # Ensure no timestamp before
        conn = db()
        conn.execute("UPDATE users SET password_changed_at = NULL WHERE id = 1")
        conn.commit()
        conn.close()

        rows = db_rows("SELECT password_changed_at FROM users WHERE id = 1")
        assert rows[0]["password_changed_at"] is None

        # Change password
        new_hash = users.hash_password("NewPassword456")
        users.update_user_password(1, new_hash)

        rows = db_rows("SELECT password_changed_at FROM users WHERE id = 1")
        assert rows[0]["password_changed_at"] is not None


class TestSessionInvalidation:
    def test_old_session_rejected_after_password_change(self):
        """A session created before password_changed_at should be invalidated."""
        from config import SESSION_TTL_DAYS
        from datetime import datetime

        # 1. Create a session cookie (simulates login)
        cookie = session.sign_session(user_id=1, issuer_id=1)
        data = session.verify_session(cookie, include_expiry=True)
        assert data is not None
        session_expiry = data[3]

        # 2. Simulate password change AFTER session was created
        #    Set password_changed_at to 2 seconds after session creation time.
        session_created = session_expiry - SESSION_TTL_DAYS * 86400
        pw_change_time = datetime.utcfromtimestamp(session_created + 2)
        pw_change_str = pw_change_time.strftime("%Y-%m-%d %H:%M:%S")
        conn = db()
        conn.execute(
            "UPDATE users SET password_changed_at = ? WHERE id = 1",
            (pw_change_str,),
        )
        conn.commit()
        conn.close()

        # 3. Check: session should be invalidated
        assert _session_invalidated_by_password_change(1, session_expiry) is True

    def test_new_session_valid_after_password_change(self):
        """A session created AFTER password_changed_at should remain valid."""
        from datetime import datetime, timedelta, timezone

        # Set password_changed_at to 1 hour ago
        pw_change_time = datetime.now(timezone.utc) - timedelta(hours=1)
        pw_change_str = pw_change_time.strftime("%Y-%m-%d %H:%M:%S")
        conn = db()
        conn.execute(
            "UPDATE users SET password_changed_at = ? WHERE id = 1",
            (pw_change_str,),
        )
        conn.commit()
        conn.close()

        # Create a fresh session (expiry is in the future, created = now)
        cookie = session.sign_session(user_id=1, issuer_id=1)
        data = session.verify_session(cookie, include_expiry=True)
        session_expiry = data[3]

        # Session was created now, password was changed 1 hour ago -> session is valid
        assert _session_invalidated_by_password_change(1, session_expiry) is False

    def test_no_password_change_session_valid(self):
        """When password_changed_at is NULL, session should remain valid."""
        conn = db()
        conn.execute("UPDATE users SET password_changed_at = NULL WHERE id = 1")
        conn.commit()
        conn.close()

        cookie = session.sign_session(user_id=1, issuer_id=1)
        data = session.verify_session(cookie, include_expiry=True)
        session_expiry = data[3]

        assert _session_invalidated_by_password_change(1, session_expiry) is False
