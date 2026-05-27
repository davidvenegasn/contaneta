"""Tests for SQLite retry-on-lock logic in database.py."""
import sqlite3
from unittest.mock import MagicMock, patch

import pytest

from database import _is_locked_error, db_rows, db_execute


class TestIsLockedError:
    """Verify lock detection helper."""

    def test_should_detect_locked_error(self):
        err = sqlite3.OperationalError("database is locked")
        assert _is_locked_error(err) is True

    def test_should_detect_locked_case_insensitive(self):
        err = sqlite3.OperationalError("Database Is Locked")
        assert _is_locked_error(err) is True

    def test_should_reject_non_locked_error(self):
        err = sqlite3.OperationalError("no such table: foo")
        assert _is_locked_error(err) is False

    def test_should_reject_non_operational_error(self):
        err = ValueError("database is locked")
        assert _is_locked_error(err) is False


class TestDbRowsRetry:
    """Verify db_rows retries on lock."""

    @patch("database.db")
    @patch("database.time.sleep")
    def test_should_retry_on_lock_then_succeed(self, mock_sleep, mock_db):
        """First call locked, second succeeds."""
        conn_fail = MagicMock()
        conn_fail.execute.side_effect = sqlite3.OperationalError("database is locked")
        conn_ok = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [{"id": 1}]
        conn_ok.execute.return_value = mock_cursor

        mock_db.side_effect = [conn_fail, conn_ok]
        result = db_rows("SELECT 1 AS id")
        assert result == [{"id": 1}]
        assert mock_sleep.call_count == 1
        conn_fail.close.assert_called_once()
        conn_ok.close.assert_called_once()

    @patch("database.db")
    def test_should_raise_after_max_retries(self, mock_db):
        """All attempts locked → raises OperationalError."""
        conn = MagicMock()
        conn.execute.side_effect = sqlite3.OperationalError("database is locked")
        mock_db.return_value = conn

        with pytest.raises(sqlite3.OperationalError, match="locked"):
            db_rows("SELECT 1")

    @patch("database.db")
    def test_should_not_retry_non_lock_errors(self, mock_db):
        """Non-lock errors should propagate immediately."""
        conn = MagicMock()
        conn.execute.side_effect = sqlite3.OperationalError("no such table")
        mock_db.return_value = conn

        with pytest.raises(sqlite3.OperationalError, match="no such table"):
            db_rows("SELECT 1")


class TestDbExecuteRetry:
    """Verify db_execute retries on lock."""

    @patch("database.db")
    @patch("database.time.sleep")
    def test_should_retry_on_lock_then_succeed(self, mock_sleep, mock_db):
        conn_fail = MagicMock()
        conn_fail.execute.side_effect = sqlite3.OperationalError("database is locked")
        conn_ok = MagicMock()

        mock_db.side_effect = [conn_fail, conn_ok]
        db_execute("INSERT INTO t VALUES (?)", (1,))
        assert mock_sleep.call_count == 1
        conn_ok.commit.assert_called_once()

    @patch("database.db")
    def test_should_raise_after_max_retries(self, mock_db):
        conn = MagicMock()
        conn.execute.side_effect = sqlite3.OperationalError("database is locked")
        mock_db.return_value = conn

        with pytest.raises(sqlite3.OperationalError, match="locked"):
            db_execute("INSERT INTO t VALUES (?)", (1,))


class TestDbConnectionParams:
    """Verify connection parameters."""

    def test_should_set_wal_mode(self):
        from database import db
        conn = db()
        try:
            mode = conn.execute("PRAGMA journal_mode").fetchone()
            assert mode.get("journal_mode") == "wal"
        finally:
            conn.close()

    def test_should_have_busy_timeout(self):
        from database import db
        conn = db()
        try:
            bt = conn.execute("PRAGMA busy_timeout").fetchone()
            # SQLite returns column name 'timeout' for PRAGMA busy_timeout
            val = bt.get("timeout") or bt.get("busy_timeout") or 0
            assert int(val) >= 30000
        finally:
            conn.close()
