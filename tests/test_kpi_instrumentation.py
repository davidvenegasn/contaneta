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
