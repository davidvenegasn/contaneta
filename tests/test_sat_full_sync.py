"""Tests for atomic full-sync pipeline handler."""
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

if not os.environ.get("APP_DB_PATH"):
    _fd, _p = tempfile.mkstemp(suffix=".db", prefix="test_full_sync_")
    os.close(_fd)
    os.environ["APP_DB_PATH"] = _p
if not os.environ.get("SESSION_SECRET"):
    os.environ["SESSION_SECRET"] = "test-secret-full-sync"

import pytest

from config import DB_PATH
from database import db
from migrations_runner import apply_migrations
from services.sat.sat_full_sync import handle_sat_full_sync

ISSUER_ID = 8890


@pytest.fixture(scope="module", autouse=True)
def seed():
    apply_migrations(DB_PATH)
    conn = db()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO issuers (id, rfc, razon_social, active, created_at, updated_at) "
            "VALUES (?, 'XAXX010101000', 'FullSync Test SA', 1, datetime('now'), datetime('now'))",
            (ISSUER_ID,),
        )
        conn.execute(
            "INSERT OR IGNORE INTO sat_sync_state "
            "(issuer_id, direction, last_sync_from, last_sync_to) "
            "VALUES (?, 'issued', '2026-01-01', '2026-05-01')",
            (ISSUER_ID,),
        )
        conn.commit()
    finally:
        conn.close()
    yield


def _make_ctx():
    ctx = MagicMock()
    ctx.progress = MagicMock()
    return ctx


def _make_job(direction="issued", backfill_days=180):
    return {
        "id": 999,
        "issuer_id": ISSUER_ID,
        "payload": {
            "issuer_id": ISSUER_ID,
            "direction": direction,
            "backfill_days": backfill_days,
        },
    }


@patch("services.sat.sat_full_sync._run_xml_pipeline", return_value=(True, "ok"))
@patch("services.sat.sat_full_sync._run_sync_php", return_value=(True, "synced 5 CFDIs"))
@patch("services.sat.sat_full_sync._update_sync_state")
def test_should_run_all_phases_in_order(mock_state, mock_sync, mock_xml):
    """Full sync calls metadata sync then XML pipeline in order."""
    ctx = _make_ctx()
    result = handle_sat_full_sync(_make_job(), ctx)
    assert result["ok"] is True
    assert result["metadata_synced"] is True
    assert result["xml_pipeline_ok"] is True
    mock_sync.assert_called_once()
    mock_xml.assert_called()
    mock_state.assert_called()


@patch("services.sat.sat_full_sync._run_xml_pipeline")
@patch("services.sat.sat_full_sync._run_sync_php", return_value=(True, "ok"))
@patch("services.sat.sat_full_sync._update_sync_state")
@patch("services.sat.sat_full_sync.count_metadata_only")
@patch("services.sat.sat_full_sync.time.sleep")
def test_should_retry_when_xml_fails_but_metadata_exists(mock_sleep, mock_count, mock_state, mock_sync, mock_xml):
    """If XML pipeline fails but metadata-only CFDIs exist, retry up to 3 times."""
    # Call 1: pre_counts after metadata sync — has metadata-only
    # Call 2: post_counts after 1st XML failure — still has metadata-only -> retry
    # Call 3: post_counts after 2nd XML failure — still has metadata-only -> retry
    mock_count.side_effect = [
        {"issued_metadata_only": 5, "issued_parsed": 10, "received_metadata_only": 0, "received_parsed": 0},
        {"issued_metadata_only": 3, "issued_parsed": 12, "received_metadata_only": 0, "received_parsed": 0},
        {"issued_metadata_only": 1, "issued_parsed": 14, "received_metadata_only": 0, "received_parsed": 0},
    ]
    # XML pipeline fails first two attempts, succeeds third
    mock_xml.side_effect = [(False, "Sin informacion"), (False, "Sin informacion"), (True, "ok")]

    ctx = _make_ctx()
    result = handle_sat_full_sync(_make_job(), ctx)
    assert result["ok"] is True
    assert result["retries"] >= 1
    assert mock_xml.call_count == 3


@patch("services.sat.sat_full_sync._run_xml_pipeline", return_value=(True, "ok"))
@patch("services.sat.sat_full_sync._run_sync_php", return_value=(True, "ok"))
@patch("services.sat.sat_full_sync._update_sync_state")
def test_should_return_stats_per_phase(mock_state, mock_sync, mock_xml):
    """Result dict includes metadata_synced, xml_pipeline_ok, retries, errors."""
    ctx = _make_ctx()
    result = handle_sat_full_sync(_make_job(), ctx)
    assert "metadata_synced" in result
    assert "xml_pipeline_ok" in result
    assert "retries" in result
    assert "errors" in result
    assert isinstance(result["errors"], list)
