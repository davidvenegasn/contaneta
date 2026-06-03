"""Tests for SAT sync priority scoring."""

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

if not os.environ.get("APP_DB_PATH"):
    _fd, _p = tempfile.mkstemp(suffix=".db", prefix="test_sat_priority_")
    os.close(_fd)
    os.environ["APP_DB_PATH"] = _p
if not os.environ.get("SESSION_SECRET"):
    os.environ["SESSION_SECRET"] = "test-secret-sat-priority"

import database  # noqa: E402
from config import DB_PATH  # noqa: E402
from migrations_runner import apply_migrations  # noqa: E402
from services.sat.sat_priority import compute_priority, is_user_active_recently  # noqa: E402

ISSUER_ID = 90100


@pytest.fixture(scope="module", autouse=True)
def setup_db():
    apply_migrations(DB_PATH)
    conn = database.db()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO issuers (id, rfc, razon_social, active, created_at, updated_at) "
            "VALUES (?, 'PRIO010101AAA', 'Priority Test SA', 1, datetime('now'), datetime('now'))",
            (ISSUER_ID,),
        )
        conn.commit()
    finally:
        conn.close()
    yield


def _current_ym() -> str:
    from datetime import date
    today = date.today()
    return f"{today.year:04d}-{today.month:02d}"


def _prev_ym(months_ago: int) -> str:
    from datetime import date
    from dateutil.relativedelta import relativedelta
    d = date.today() - relativedelta(months=months_ago)
    return f"{d.year:04d}-{d.month:02d}"


def test_compute_priority_current_month_active_user_returns_1():
    """Current month + active user should get priority 1 (most urgent)."""
    p = compute_priority(ISSUER_ID, _current_ym(), user_active_recently=True)
    assert p == 1


def test_compute_priority_current_month_inactive_returns_6():
    """Current month + inactive user should get priority 6."""
    p = compute_priority(ISSUER_ID, _current_ym(), user_active_recently=False)
    assert p == 6


def test_compute_priority_last_month_active_returns_20():
    """Last month + active user should get priority 20."""
    p = compute_priority(ISSUER_ID, _prev_ym(1), user_active_recently=True)
    assert p == 20


def test_compute_priority_old_month_inactive_returns_high():
    """6 months ago + inactive should return >= 106."""
    p = compute_priority(ISSUER_ID, _prev_ym(6), user_active_recently=False)
    assert p >= 106


def test_compute_priority_invalid_ym_returns_very_high():
    """Invalid ym format should return very high priority (deprioritized)."""
    p = compute_priority(ISSUER_ID, "bad-format", user_active_recently=True)
    assert p > 100


def test_enqueue_assigns_priority():
    """enqueue_sat_sync should store priority in sat_jobs."""
    from services.sat.sat_autosync import enqueue_sat_sync
    # Clean stale sat_jobs to avoid global rate limit
    conn = database.db()
    try:
        conn.execute(
            "UPDATE sat_jobs SET status = 'ok', created_at = datetime('now', '-2 hours') "
            "WHERE status = 'queued'"
        )
        conn.execute("DELETE FROM sat_jobs WHERE issuer_id = ?", (ISSUER_ID,))
        conn.commit()
    finally:
        conn.close()

    jid = enqueue_sat_sync(ISSUER_ID, "issued", priority=5)
    assert jid is not None and jid > 0

    conn = database.db()
    try:
        row = conn.execute(
            "SELECT priority FROM sat_jobs WHERE id = ?", (jid,)
        ).fetchone()
        assert row is not None
        assert row["priority"] == 5
    finally:
        conn.close()

    # Clean up
    conn = database.db()
    try:
        conn.execute("DELETE FROM sat_jobs WHERE issuer_id = ?", (ISSUER_ID,))
        conn.commit()
    finally:
        conn.close()


def test_is_user_active_recently_returns_false_without_audit():
    """No audit_log entries → not active."""
    active = is_user_active_recently(ISSUER_ID, days=7)
    assert active is False
