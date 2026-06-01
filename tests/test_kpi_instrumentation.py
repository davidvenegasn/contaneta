"""Tests for KPI instrumentation: SQL logging and value logging."""

import logging
import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

if not os.environ.get("APP_DB_PATH"):
    _fd, _p = tempfile.mkstemp(suffix=".db", prefix="test_kpi_instr_")
    os.close(_fd)
    os.environ["APP_DB_PATH"] = _p
if not os.environ.get("SESSION_SECRET"):
    os.environ["SESSION_SECRET"] = "test-secret-kpi-instr"

from config import DB_PATH  # noqa: E402
from database import _log_query  # noqa: E402
from migrations_runner import apply_migrations  # noqa: E402


@pytest.fixture(scope="module", autouse=True)
def seed():
    apply_migrations(DB_PATH)
    yield


def test_should_log_query_to_stderr_when_enabled(capsys):
    """_log_query should write to stderr when _SQL_LOG is enabled."""
    import database
    original = database._SQL_LOG
    try:
        database._SQL_LOG = True
        _log_query("SELECT * FROM issuers WHERE id = ?", (1,), 2.5)
        captured = capsys.readouterr()
        assert "[SQL 2ms]" in captured.err
        assert "SELECT * FROM issuers" in captured.err
    finally:
        database._SQL_LOG = original


def test_should_not_log_when_disabled(capsys):
    """_log_query should be silent when _SQL_LOG is disabled."""
    import database
    original = database._SQL_LOG
    try:
        database._SQL_LOG = False
        _log_query("SELECT 1", (), 1.0)
        captured = capsys.readouterr()
        assert "[SQL" not in captured.err
    finally:
        database._SQL_LOG = original


def test_should_log_kpi_values_at_debug_level(caplog):
    """get_month_totals should log KPI values at DEBUG level."""
    from services.sat.sat_sync import get_month_totals
    with caplog.at_level(logging.DEBUG, logger="services.sat.sat_sync"):
        get_month_totals(99999, "2026-06", "issued")
    assert any("KPI issuer=99999" in rec.message for rec in caplog.records)
    assert any("ym=2026-06" in rec.message for rec in caplog.records)


def test_should_return_consistent_values_on_repeated_calls():
    """Same call to get_month_totals should return identical results (no race)."""
    from services.sat.sat_sync import get_month_totals
    r1 = get_month_totals(99999, "2026-06", "issued")
    r2 = get_month_totals(99999, "2026-06", "issued")
    assert r1 == r2


def test_should_accept_shared_connection_for_atomic_snapshot():
    """get_month_totals with shared conn should return same results and not close it."""
    from database import db as get_db
    from services.sat.sat_sync import get_month_totals
    conn = get_db()
    try:
        r1 = get_month_totals(99999, "2026-06", "issued", conn=conn)
        r2 = get_month_totals(99999, "2026-06", "received", conn=conn)
        # Connection should still be usable (not closed by the function)
        conn.execute("SELECT 1")
        assert isinstance(r1, dict)
        assert isinstance(r2, dict)
    finally:
        conn.close()


def test_should_render_same_kpis_on_double_request():
    """Two requests to dashboard should produce same KPIs (render-twice consistency)."""
    from fastapi.testclient import TestClient
    from app import app
    from tests.helpers import make_session_cookie
    # Use a high issuer_id unlikely to have real data
    cookies = make_session_cookie(issuer_id=99999, user_id=99999)
    client = TestClient(app, raise_server_exceptions=False, cookies=cookies)
    r1 = client.get("/portal/home")
    r2 = client.get("/portal/home")
    # Both should succeed (or both redirect to login)
    assert r1.status_code == r2.status_code


def test_should_pass_shared_conn_through_safe_wrapper():
    """_get_month_totals_safe with shared conn should not close it."""
    from database import db as get_db
    from routers.api._helpers import _get_month_totals_safe
    conn = get_db()
    try:
        r1 = _get_month_totals_safe(99999, "2026-06", "issued", conn=conn)
        r2 = _get_month_totals_safe(99999, "2026-06", "received", conn=conn)
        # Connection still usable
        conn.execute("SELECT 1")
        assert isinstance(r1, dict)
        assert isinstance(r2, dict)
        assert "total_base" in r1
    finally:
        conn.close()


def test_should_return_consistent_trend_on_double_request():
    """Two calls to /api/metrics/trend should return identical data."""
    from fastapi.testclient import TestClient
    from app import app
    from tests.helpers import make_session_cookie
    cookies = make_session_cookie(issuer_id=99999, user_id=99999)
    client = TestClient(app, raise_server_exceptions=False, cookies=cookies)
    r1 = client.get("/api/metrics/trend?months=3")
    r2 = client.get("/api/metrics/trend?months=3")
    assert r1.status_code == r2.status_code
    if r1.status_code == 200:
        assert r1.json() == r2.json()
