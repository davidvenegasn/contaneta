"""Tests for SAT history chooser: smart defaults and start-history-sync endpoint."""

import os
import sys
import tempfile
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

if not os.environ.get("APP_DB_PATH"):
    _fd, _p = tempfile.mkstemp(suffix=".db", prefix="test_history_chooser_")
    os.close(_fd)
    os.environ["APP_DB_PATH"] = _p
if not os.environ.get("SESSION_SECRET"):
    os.environ["SESSION_SECRET"] = "test-secret-history-chooser"

from fastapi.testclient import TestClient  # noqa: E402

from app import app  # noqa: E402
from config import DB_PATH  # noqa: E402
from database import db, has_column  # noqa: E402
from migrations_runner import apply_migrations  # noqa: E402
from tests.helpers import make_session_cookie  # noqa: E402

ISSUER_ID = 8100
USER_ID = 8100


def _ensure_validation_columns(conn):
    for col, col_type in [("validation_at", "TEXT"), ("validation_ok", "INTEGER"), ("validation_message", "TEXT")]:
        if not has_column(conn, "sat_credentials", col):
            conn.execute(f"ALTER TABLE sat_credentials ADD COLUMN {col} {col_type};")


@pytest.fixture(scope="module", autouse=True)
def seed():
    apply_migrations(DB_PATH)
    conn = db()
    try:
        conn.execute(
            "INSERT INTO issuers (id, rfc, razon_social, active, created_at, updated_at) "
            "VALUES (?, 'HIST010101AAA', 'History Test SA', 1, datetime('now'), datetime('now')) "
            "ON CONFLICT(id) DO UPDATE SET rfc = excluded.rfc",
            (ISSUER_ID,),
        )
        conn.execute(
            "INSERT OR IGNORE INTO users (id, email, password_hash, created_at) "
            "VALUES (?, 'history@test.local', 'x', datetime('now'))",
            (USER_ID,),
        )
        conn.execute(
            "INSERT OR IGNORE INTO memberships (user_id, issuer_id, role, created_at) "
            "VALUES (?, ?, 'owner', datetime('now'))",
            (USER_ID, ISSUER_ID),
        )
        _ensure_validation_columns(conn)
        conn.execute(
            "INSERT OR IGNORE INTO sat_credentials "
            "(issuer_id, fiel_cer_path, fiel_key_path, fiel_key_password, "
            "validation_ok, validation_at, created_at, updated_at) "
            "VALUES (?, 'fake.cer.enc', 'fake.key.enc', 'enc:x', "
            "1, datetime('now'), datetime('now'), datetime('now'))",
            (ISSUER_ID,),
        )
        conn.commit()
    finally:
        conn.close()
    yield


@pytest.fixture(scope="module")
def client():
    cookies = make_session_cookie(issuer_id=ISSUER_ID, user_id=USER_ID)
    return TestClient(app, raise_server_exceptions=False, cookies=cookies)


# ── Smart default tests ──


def _make_mock_date(year, month, day):
    """Create a date subclass with a fixed today() for patching datetime.date."""
    import datetime

    class MockDate(datetime.date):
        @classmethod
        def today(cls):
            return cls(year, month, day)
    return MockDate


def test_should_return_last_3_months_in_january():
    """default_history_option returns 'last_3_months' for Jan-Mar."""
    from services.sat.sat_autosync import default_history_option

    with patch("datetime.date", _make_mock_date(2026, 1, 15)):
        assert default_history_option() == "last_3_months"


def test_should_return_current_year_in_april():
    """default_history_option returns 'current_year' for Apr+."""
    from services.sat.sat_autosync import default_history_option

    with patch("datetime.date", _make_mock_date(2026, 4, 10)):
        assert default_history_option() == "current_year"


# ── Endpoint tests ──


def test_should_block_full_5_years_for_free_plan(client):
    """POST start-history-sync with full_5_years on non-pro plan returns 403."""
    with patch("services.billing.plans.get_issuer_plan", return_value="free"):
        resp = client.post(
            "/portal/config/sat/start-history-sync",
            json={"history_option": "full_5_years"},
            headers={"Accept": "application/json"},
        )
    assert resp.status_code == 403
    body = resp.json()
    assert body["ok"] is False
    assert "Pro" in body["message"]


def test_should_calculate_correct_start_date_for_history_sync(client):
    """POST start-history-sync with valid option returns ok and start_date."""
    with patch("services.sat.sat_full_sync.enqueue_sat_full_sync", return_value=99):
        resp = client.post(
            "/portal/config/sat/start-history-sync",
            json={"history_option": "last_3_months"},
            headers={"Accept": "application/json"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert "start_date" in body
    assert body["start_date"].startswith("20")
    assert len(body["job_ids"]) >= 2


def test_should_allow_full_5_years_for_pro_plan(client):
    """POST start-history-sync with full_5_years on pro plan returns 200."""
    with patch("services.billing.plans.get_issuer_plan", return_value="pro"), \
         patch("services.sat.sat_full_sync.enqueue_sat_full_sync", return_value=99):
        resp = client.post(
            "/portal/config/sat/start-history-sync",
            json={"history_option": "full_5_years"},
            headers={"Accept": "application/json"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert len(body["job_ids"]) >= 2


def test_should_render_expand_button_on_config_page(client):
    """GET /portal/config/sat should include the expand history button."""
    resp = client.get("/portal/config/sat")
    assert resp.status_code == 200
    assert b"satExpandHistoryBtn" in resp.content
    assert b"Ampliar historial" in resp.content


def test_should_reject_invalid_history_option(client):
    """POST start-history-sync with invalid option returns 400."""
    resp = client.post(
        "/portal/config/sat/start-history-sync",
        json={"history_option": "invalid_option"},
        headers={"Accept": "application/json"},
    )
    assert resp.status_code == 400
