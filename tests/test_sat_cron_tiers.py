"""Tests for multi-tier SAT cron enqueue functions."""

import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

if not os.environ.get("APP_DB_PATH"):
    _fd, _p = tempfile.mkstemp(suffix=".db", prefix="test_sat_cron_")
    os.close(_fd)
    os.environ["APP_DB_PATH"] = _p
if not os.environ.get("SESSION_SECRET"):
    os.environ["SESSION_SECRET"] = "test-secret-sat-cron"

import database  # noqa: E402
from config import DB_PATH  # noqa: E402
from migrations_runner import apply_migrations  # noqa: E402

ISSUER_ID = 90200


@pytest.fixture(scope="module", autouse=True)
def setup_db():
    apply_migrations(DB_PATH)
    conn = database.db()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO issuers (id, rfc, razon_social, active, created_at, updated_at) "
            "VALUES (?, 'CRON010101AAA', 'Cron Test SA', 1, datetime('now'), datetime('now'))",
            (ISSUER_ID,),
        )
        # Add validated FIEL credential
        conn.execute(
            "INSERT OR IGNORE INTO sat_credentials (issuer_id, validation_ok, created_at, updated_at) "
            "VALUES (?, 1, datetime('now'), datetime('now'))",
            (ISSUER_ID,),
        )
        conn.commit()
    finally:
        conn.close()
    yield


def _clean_sat_jobs():
    conn = database.db()
    try:
        conn.execute("DELETE FROM sat_jobs WHERE issuer_id = ?", (ISSUER_ID,))
        conn.execute(
            "UPDATE sat_jobs SET status = 'ok', created_at = datetime('now', '-2 hours') "
            "WHERE status = 'queued'"
        )
        conn.commit()
    finally:
        conn.close()


def test_enqueue_current_month_skips_if_job_already_queued():
    """Should not double-enqueue for same issuer+direction."""
    _clean_sat_jobs()
    from services.sat.sat_autosync import enqueue_active_issuers_current_month

    n1 = enqueue_active_issuers_current_month()
    assert n1 > 0

    # Second call should skip (dedupe)
    n2 = enqueue_active_issuers_current_month()
    assert n2 == 0

    _clean_sat_jobs()


def test_enqueue_last_3_months_creates_jobs_per_direction_per_month():
    """Should create up to 6 jobs (3 months x 2 directions) per issuer."""
    _clean_sat_jobs()
    from services.sat.sat_autosync import enqueue_active_issuers_last_3_months

    n = enqueue_active_issuers_last_3_months()
    # At least 2 jobs (current month issued+received), up to 6
    assert n >= 2
    assert n <= 6

    _clean_sat_jobs()


def test_cron_scripts_are_executable():
    """All sat_cron_*.sh scripts must exist and be executable."""
    for name in ("sat_cron_hourly.sh", "sat_cron_daily.sh", "sat_cron_weekly.sh"):
        script = ROOT / "scripts" / name
        assert script.exists(), f"scripts/{name} not found"
        assert os.access(script, os.X_OK), f"scripts/{name} is not executable"
