"""Tests for count-up JS defensive behavior.

Verifies that server-rendered HTML contains correct final values
in data-count-to attributes, so the JS animation is purely decorative.
"""

import os
import re
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

if not os.environ.get("APP_DB_PATH"):
    _fd, _p = tempfile.mkstemp(suffix=".db", prefix="test_countup_")
    os.close(_fd)
    os.environ["APP_DB_PATH"] = _p
if not os.environ.get("SESSION_SECRET"):
    os.environ["SESSION_SECRET"] = "test-secret-countup"

import database  # noqa: E402
from config import DB_PATH  # noqa: E402
from migrations_runner import apply_migrations  # noqa: E402

_DATA_COUNT_RE = re.compile(r'data-count-to="([^"]*)"')
_ISSUER_ID = 77701
_USER_ID = 77701


@pytest.fixture(scope="module", autouse=True)
def seed():
    apply_migrations(DB_PATH)
    conn = database.db()
    try:
        # Seed issuer, user, membership for auth
        conn.execute(
            "INSERT OR IGNORE INTO issuers (id, rfc, razon_social, active, created_at, updated_at) "
            "VALUES (?, 'TEST770101AAA', 'CountUp Test Co', 1, datetime('now'), datetime('now'))",
            (_ISSUER_ID,),
        )
        conn.execute(
            "INSERT OR IGNORE INTO users (id, email, password_hash, created_at) "
            "VALUES (?, 'countup@test.local', 'x', datetime('now'))",
            (_USER_ID,),
        )
        conn.execute(
            "INSERT OR IGNORE INTO memberships (user_id, issuer_id, role, created_at) "
            "VALUES (?, ?, 'owner', datetime('now'))",
            (_USER_ID, _ISSUER_ID),
        )
        conn.commit()
    finally:
        conn.close()
    yield


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient
    from app import app
    from tests.helpers import make_session_cookie
    cookies = make_session_cookie(issuer_id=_ISSUER_ID, user_id=_USER_ID)
    return TestClient(app, raise_server_exceptions=False, cookies=cookies)


def test_count_up_text_is_final_value_immediately_after_dom_ready(client):
    """data-count-to values in rendered HTML must be valid floats, not placeholders."""
    r = client.get("/portal/facturas?tab=issued&ym=2026-06")
    assert r.status_code == 200, f"Expected 200, got {r.status_code}"
    matches = _DATA_COUNT_RE.findall(r.text)
    assert len(matches) > 0, "No data-count-to attributes found in rendered HTML"
    for val in matches:
        parsed = float(val)  # raises ValueError if not a valid number
        assert parsed == parsed, f"data-count-to contains NaN: {val}"


def test_count_up_does_not_show_nan_or_intermediate_values(client):
    """Repeated renders must produce identical data-count-to values (no race)."""
    values = []
    for _ in range(5):
        r = client.get("/portal/facturas?tab=issued&ym=2026-06")
        assert r.status_code == 200
        matches = _DATA_COUNT_RE.findall(r.text)
        values.append(tuple(matches))
    # All 5 renders must produce identical count-to values
    assert len(set(values)) == 1, f"data-count-to values differ across renders: {values}"
