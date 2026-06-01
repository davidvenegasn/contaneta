"""Tests for metadata-only CFDI detection and repair service + admin endpoint."""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

if not os.environ.get("APP_DB_PATH"):
    _fd, _p = tempfile.mkstemp(suffix=".db", prefix="test_sat_repair_")
    os.close(_fd)
    os.environ["APP_DB_PATH"] = _p
if not os.environ.get("SESSION_SECRET"):
    os.environ["SESSION_SECRET"] = "test-secret-sat-repair"

import pytest
from fastapi.testclient import TestClient

from app import app
from config import DB_PATH
from database import db
from migrations_runner import apply_migrations
from services.sat.sat_metadata_only_repair import (
    count_metadata_only,
    find_metadata_only_cfdis,
    reset_checkpoint_for_repair,
)
from tests.helpers import make_session_cookie

ISSUER_ID = 8880
USER_ID = 8880


@pytest.fixture(scope="module", autouse=True)
def seed():
    """Create issuer, user, membership, CFDIs, and sync state."""
    apply_migrations(DB_PATH)
    conn = db()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO issuers (id, rfc, razon_social, active, created_at, updated_at) "
            "VALUES (?, 'XAXX010101000', 'Repair Test SA', 1, datetime('now'), datetime('now'))",
            (ISSUER_ID,),
        )
        conn.execute(
            "INSERT OR IGNORE INTO users (id, email, password_hash, created_at) "
            "VALUES (?, 'repair@test.local', 'x', datetime('now'))",
            (USER_ID,),
        )
        conn.execute(
            "INSERT OR IGNORE INTO memberships (user_id, issuer_id, role, created_at) "
            "VALUES (?, ?, 'owner', datetime('now'))",
            (USER_ID, ISSUER_ID),
        )
        # Parsed CFDI — should NOT appear in metadata-only list
        conn.execute(
            "INSERT OR IGNORE INTO sat_cfdi "
            "(issuer_id, direction, uuid, fecha_emision, total, xml_status, status) "
            "VALUES (?, 'issued', 'repair-parsed-001', '2026-03-10', 1000.0, 'parsed', '1')",
            (ISSUER_ID,),
        )
        # Metadata-only CFDI (no XML)
        conn.execute(
            "INSERT OR IGNORE INTO sat_cfdi "
            "(issuer_id, direction, uuid, fecha_emision, total, xml_status, status) "
            "VALUES (?, 'issued', 'repair-meta-002', '2026-03-11', 0.0, NULL, '1')",
            (ISSUER_ID,),
        )
        # Another metadata-only (received)
        conn.execute(
            "INSERT OR IGNORE INTO sat_cfdi "
            "(issuer_id, direction, uuid, fecha_emision, total, xml_status, status, rfc_emisor, nombre_emisor) "
            "VALUES (?, 'received', 'repair-meta-003', '2026-03-12', 500.0, 'metadata', '1', 'XAXX', 'Test')",
            (ISSUER_ID,),
        )
        # Sync state row for checkpoint reset test
        conn.execute(
            "INSERT OR IGNORE INTO sat_sync_state "
            "(issuer_id, direction, last_sync_from, last_sync_to) "
            "VALUES (?, 'issued', '2026-05-01 00:00:00', '2026-05-28 00:00:00')",
            (ISSUER_ID,),
        )
        conn.commit()
    finally:
        conn.close()
    yield


def test_should_find_metadata_only_returns_only_unparsed():
    """find_metadata_only_cfdis should return only CFDIs without xml_status='parsed'."""
    cfdis = find_metadata_only_cfdis(ISSUER_ID)
    uuids = [c["uuid"] for c in cfdis]
    assert "repair-meta-002" in uuids
    assert "repair-meta-003" in uuids
    assert "repair-parsed-001" not in uuids


def test_should_count_metadata_only_by_direction():
    """count_metadata_only should break down counts by direction."""
    counts = count_metadata_only(ISSUER_ID)
    assert counts["issued_parsed"] >= 1
    assert counts["issued_metadata_only"] >= 1
    assert counts["received_metadata_only"] >= 1


def test_should_reset_checkpoint_to_january():
    """reset_checkpoint_for_repair should update last_sync_from/to and clear cooldown."""
    reset_checkpoint_for_repair(ISSUER_ID, "2026-01-01 00:00:00")
    conn = db()
    try:
        row = conn.execute(
            "SELECT last_sync_from, last_sync_to, cooldown_until "
            "FROM sat_sync_state WHERE issuer_id = ? AND direction = 'issued'",
            (ISSUER_ID,),
        ).fetchone()
        assert row is not None
        assert row["last_sync_from"] == "2026-01-01 00:00:00"
        assert row["last_sync_to"] == "2026-01-01 00:00:00"
        assert row["cooldown_until"] is None
    finally:
        conn.close()


def test_should_admin_repair_endpoint_require_admin_role():
    """POST /admin/sat/repair-metadata-only should reject non-admin users."""
    # Use owner role (not admin) — should fail with 403
    cookies = make_session_cookie(issuer_id=ISSUER_ID, user_id=USER_ID)
    client = TestClient(app, raise_server_exceptions=False, cookies=cookies)
    r = client.post("/admin/sat/repair-metadata-only", json={"issuer_id": ISSUER_ID})
    assert r.status_code == 403
