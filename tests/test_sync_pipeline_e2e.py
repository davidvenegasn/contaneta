"""E2E tests for the SAT sync pipeline + portal filter integration.

Validates the full flow: metadata sync creates metadata-only CFDIs,
portal filter hides them, repair service detects them, API status
reports counts, and full resync endpoint is accessible.
"""
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

if not os.environ.get("APP_DB_PATH"):
    _fd, _p = tempfile.mkstemp(suffix=".db", prefix="test_pipeline_e2e_")
    os.close(_fd)
    os.environ["APP_DB_PATH"] = _p
if not os.environ.get("SESSION_SECRET"):
    os.environ["SESSION_SECRET"] = "test-secret-pipeline-e2e"

import pytest
from fastapi.testclient import TestClient

from app import app
from config import DB_PATH
from database import db, db_rows
from migrations_runner import apply_migrations
from tests.helpers import make_session_cookie

ISSUER_ID = 9800
USER_ID = 9800
YM = "2026-04"


@pytest.fixture(scope="module", autouse=True)
def seed():
    """Create issuer, user, membership, sat_credentials, and test CFDIs."""
    apply_migrations(DB_PATH)
    conn = db()
    try:
        conn.execute(
            "INSERT INTO issuers (id, rfc, razon_social, active, created_at, updated_at) "
            "VALUES (?, 'XYZ010101AAA', 'Pipeline E2E SA', 1, datetime('now'), datetime('now')) "
            "ON CONFLICT(id) DO UPDATE SET rfc = excluded.rfc, razon_social = excluded.razon_social",
            (ISSUER_ID,),
        )
        conn.execute(
            "INSERT OR IGNORE INTO users (id, email, password_hash, created_at) "
            "VALUES (?, 'pipeline_e2e@test.local', 'x', datetime('now'))",
            (USER_ID,),
        )
        conn.execute(
            "INSERT OR IGNORE INTO memberships (user_id, issuer_id, role, created_at) "
            "VALUES (?, ?, 'owner', datetime('now'))",
            (USER_ID, ISSUER_ID),
        )
        # SAT credentials (needed for full-resync endpoint)
        conn.execute(
            "INSERT OR IGNORE INTO sat_credentials "
            "(issuer_id, fiel_cer_path, fiel_key_path, fiel_key_password, "
            "validation_ok, validation_at, created_at, updated_at) "
            "VALUES (?, 'fake.cer.enc', 'fake.key.enc', 'enc:x', "
            "1, datetime('now'), datetime('now'), datetime('now'))",
            (ISSUER_ID,),
        )
        # Sync state
        conn.execute(
            "INSERT OR REPLACE INTO sat_sync_state "
            "(issuer_id, direction, last_sync_from, last_sync_to, last_success_at) "
            "VALUES (?, 'issued', '2026-01-01', '2026-04-30', datetime('now'))",
            (ISSUER_ID,),
        )

        # Simulate post-metadata-sync state: mix of parsed and metadata-only
        # Parsed (total from XML) — should always show
        conn.execute(
            "INSERT OR IGNORE INTO sat_cfdi "
            "(issuer_id, direction, uuid, fecha_emision, total, xml_status, status, "
            "rfc_receptor, nombre_receptor, concepto) "
            "VALUES (?, 'issued', 'e2e-parsed-001', ?, 15000.0, 'parsed', '1', "
            "'XAXX010101000', 'Cliente A', 'Servicio de consultoría')",
            (ISSUER_ID, f"{YM}-10T10:00:00"),
        )
        # Parsed with total=0 (credit note) — should show because parsed
        conn.execute(
            "INSERT OR IGNORE INTO sat_cfdi "
            "(issuer_id, direction, uuid, fecha_emision, total, xml_status, status, "
            "rfc_receptor, nombre_receptor, concepto) "
            "VALUES (?, 'issued', 'e2e-parsed-zero-002', ?, 0.0, 'parsed', '1', "
            "'XAXX010101000', 'Cliente B', 'Nota de crédito')",
            (ISSUER_ID, f"{YM}-11T10:00:00"),
        )
        # Metadata-only, total=0 (pending XML) — should HIDE in portal
        conn.execute(
            "INSERT OR IGNORE INTO sat_cfdi "
            "(issuer_id, direction, uuid, fecha_emision, total, xml_status, status, "
            "rfc_receptor, nombre_receptor, concepto) "
            "VALUES (?, 'issued', 'e2e-meta-only-003', ?, 0.0, NULL, '1', "
            "'XAXX010101000', 'Cliente C', 'Pendiente')",
            (ISSUER_ID, f"{YM}-12T10:00:00"),
        )
        # Metadata-only, total=0, received direction
        conn.execute(
            "INSERT OR IGNORE INTO sat_cfdi "
            "(issuer_id, direction, uuid, fecha_emision, total, xml_status, status, "
            "rfc_emisor, nombre_emisor) "
            "VALUES (?, 'received', 'e2e-meta-recv-004', ?, 0.0, 'metadata', '1', "
            "'PROVEEDOR01', 'Proveedor Test')",
            (ISSUER_ID, f"{YM}-13T10:00:00"),
        )
        # Real total without XML — should show (total > 0.01)
        conn.execute(
            "INSERT OR IGNORE INTO sat_cfdi "
            "(issuer_id, direction, uuid, fecha_emision, total, xml_status, status, "
            "rfc_receptor, nombre_receptor, concepto) "
            "VALUES (?, 'issued', 'e2e-no-xml-real-005', ?, 8500.0, NULL, '1', "
            "'XAXX010101000', 'Cliente D', 'Factura sin XML')",
            (ISSUER_ID, f"{YM}-14T10:00:00"),
        )
        conn.commit()
    finally:
        conn.close()
    yield


@pytest.fixture(scope="module")
def client():
    cookies = make_session_cookie(issuer_id=ISSUER_ID, user_id=USER_ID)
    return TestClient(app, raise_server_exceptions=False, cookies=cookies)


# ── Portal filter integration ──


def test_should_show_parsed_cfdis_in_issued_list(client):
    """Parsed CFDIs (including total=0 credit notes) appear in the issued API."""
    r = client.get(f"/api/invoices/issued?ym={YM}")
    assert r.status_code == 200
    uuids = [d["uuid"] for d in r.json()["data"]]
    assert "e2e-parsed-001" in uuids
    assert "e2e-parsed-zero-002" in uuids


def test_should_hide_metadata_only_zero_total_from_issued_list(client):
    """Metadata-only CFDIs with total=0 are hidden from the issued list."""
    r = client.get(f"/api/invoices/issued?ym={YM}")
    uuids = [d["uuid"] for d in r.json()["data"]]
    assert "e2e-meta-only-003" not in uuids


def test_should_show_no_xml_cfdi_with_real_total(client):
    """CFDIs without XML but with real total still show in the list."""
    r = client.get(f"/api/invoices/issued?ym={YM}")
    uuids = [d["uuid"] for d in r.json()["data"]]
    assert "e2e-no-xml-real-005" in uuids


# ── Metadata-only repair service integration ──


def test_should_detect_metadata_only_cfdis_via_repair_service():
    """count_metadata_only should detect our test metadata-only CFDIs."""
    from services.sat.sat_metadata_only_repair import count_metadata_only
    counts = count_metadata_only(ISSUER_ID)
    assert counts["issued_metadata_only"] >= 1
    assert counts["received_metadata_only"] >= 1
    assert counts["issued_parsed"] >= 1


def test_should_find_metadata_only_cfdis_by_uuid():
    """find_metadata_only_cfdis should return the unparsed CFDIs."""
    from services.sat.sat_metadata_only_repair import find_metadata_only_cfdis
    cfdis = find_metadata_only_cfdis(ISSUER_ID)
    uuids = [c["uuid"] for c in cfdis]
    assert "e2e-meta-only-003" in uuids
    assert "e2e-meta-recv-004" in uuids
    assert "e2e-parsed-001" not in uuids


# ── API status reports metadata counts ──


def test_should_report_metadata_counts_in_sat_status(client):
    """GET /api/sat/status should include metadata-only counts for this issuer."""
    r = client.get("/api/sat/status")
    assert r.status_code == 200
    data = r.json()["data"]
    mc = data.get("metadata_counts", {})
    assert mc.get("issued_metadata_only", 0) >= 1
    assert mc.get("received_metadata_only", 0) >= 1


# ── Full resync endpoint accessible ──


def test_should_accept_full_resync_request(client):
    """POST /portal/sat/full-resync should enqueue jobs successfully."""
    r = client.post("/portal/sat/full-resync",
                    headers={"Accept": "application/json"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert len(body["job_ids"]) == 2


# ── Full sync handler pipeline (mocked PHP) ──


@patch("services.sat.sat_full_sync._run_xml_pipeline", return_value=(True, "ok"))
@patch("services.sat.sat_full_sync._run_sync_php", return_value=(True, "synced"))
@patch("services.sat.sat_full_sync._update_sync_state")
def test_should_run_full_sync_pipeline_end_to_end(mock_state, mock_sync, mock_xml):
    """Full sync pipeline should complete all phases with mocked PHP."""
    from unittest.mock import MagicMock
    from services.sat.sat_full_sync import handle_sat_full_sync

    ctx = MagicMock()
    ctx.progress = MagicMock()
    job = {
        "id": 9999,
        "issuer_id": ISSUER_ID,
        "payload": {
            "issuer_id": ISSUER_ID,
            "direction": "issued",
            "backfill_days": 365,
        },
    }
    result = handle_sat_full_sync(job, ctx)
    assert result["ok"] is True
    assert result["metadata_synced"] is True
    assert result["xml_pipeline_ok"] is True
    mock_sync.assert_called_once()
    mock_xml.assert_called()
