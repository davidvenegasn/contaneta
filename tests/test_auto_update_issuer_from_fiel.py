"""Tests for auto-update issuer fiscal data from FIEL certificate."""
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

if not os.environ.get("APP_DB_PATH"):
    _fd, _p = tempfile.mkstemp(suffix=".db", prefix="test_auto_fiel_")
    os.close(_fd)
    os.environ["APP_DB_PATH"] = _p
if not os.environ.get("SESSION_SECRET"):
    os.environ["SESSION_SECRET"] = "test-secret-auto-fiel"

import pytest

from config import DB_PATH
from database import db, db_rows
from migrations_runner import apply_migrations
from services.sat.auto_update_issuer_from_fiel import maybe_update_issuer_from_fiel

ISSUER_PENDING = 9901
ISSUER_EMPTY = 9902
ISSUER_REAL = 9903
ISSUER_CONFLICT = 9904

MOCK_SUBJECT = {
    "rfc": "AAA010101AAA",
    "nombre": "Empresa Real SA de CV",
    "expires_at": "2028-01-01T00:00:00+00:00",
    "days_until_expiry": 365,
}


@pytest.fixture(scope="module", autouse=True)
def seed():
    """Create issuers with varying RFC/razon_social states for testing."""
    apply_migrations(DB_PATH)
    conn = db()
    try:
        for iid, rfc, name in [
            (ISSUER_PENDING, "PENDIENTE", "PENDIENTE"),
            (ISSUER_EMPTY, "PENDIENTE", ""),
            (ISSUER_REAL, "AAA010101AAA", "Empresa Real SA de CV"),
            (ISSUER_CONFLICT, "BBB020202BBB", "Otra Empresa SA"),
        ]:
            conn.execute(
                "INSERT INTO issuers (id, rfc, razon_social, active, created_at, updated_at) "
                "VALUES (?, ?, ?, 1, datetime('now'), datetime('now')) "
                "ON CONFLICT(id) DO UPDATE SET rfc = excluded.rfc, razon_social = excluded.razon_social",
                (iid, rfc, name),
            )
        conn.commit()
    finally:
        conn.close()
    yield


@patch("services.sat.auto_update_issuer_from_fiel.extract_fiel_subject", return_value=MOCK_SUBJECT)
def test_should_auto_update_when_rfc_is_pending(mock_extract):
    """If current RFC is 'PENDIENTE', it should be updated from FIEL cert."""
    result = maybe_update_issuer_from_fiel(ISSUER_PENDING)
    assert result["updated"] is True
    assert result["changes"]["rfc"] == "AAA010101AAA"
    conn = db()
    try:
        row = conn.execute("SELECT rfc FROM issuers WHERE id = ?", (ISSUER_PENDING,)).fetchone()
        assert row["rfc"] == "AAA010101AAA"
    finally:
        conn.close()


@patch("services.sat.auto_update_issuer_from_fiel.extract_fiel_subject", return_value=MOCK_SUBJECT)
def test_should_auto_update_when_razon_social_is_empty(mock_extract):
    """If current razon_social is empty, it should be updated from FIEL cert."""
    result = maybe_update_issuer_from_fiel(ISSUER_EMPTY)
    assert result["updated"] is True
    assert "razon_social" in result["changes"]
    conn = db()
    try:
        row = conn.execute("SELECT razon_social FROM issuers WHERE id = ?", (ISSUER_EMPTY,)).fetchone()
        assert row["razon_social"] == "Empresa Real SA de CV"
    finally:
        conn.close()


@patch("services.sat.auto_update_issuer_from_fiel.extract_fiel_subject", return_value=MOCK_SUBJECT)
def test_should_not_overwrite_when_existing_rfc_is_real(mock_extract):
    """If current RFC matches cert RFC, no update or conflict should be reported."""
    result = maybe_update_issuer_from_fiel(ISSUER_REAL)
    assert result["updated"] is False
    assert result["changes"] == {}
    assert result["conflicts"] == []


@patch("services.sat.auto_update_issuer_from_fiel.extract_fiel_subject", return_value=MOCK_SUBJECT)
def test_should_create_conflict_notification_when_real_rfc_differs(mock_extract):
    """If current RFC is a real RFC that differs from cert, create conflict notification."""
    result = maybe_update_issuer_from_fiel(ISSUER_CONFLICT)
    assert result["updated"] is False
    assert len(result["conflicts"]) >= 1
    assert any(c["field"] == "rfc" for c in result["conflicts"])
    rows = db_rows(
        "SELECT * FROM notifications WHERE issuer_id = ? AND type = 'fiel_rfc_conflict'",
        (ISSUER_CONFLICT,),
    )
    assert len(rows) >= 1
    assert "no coinciden" in rows[0]["body"]
