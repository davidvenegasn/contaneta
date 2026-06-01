"""Tests for flexible CFDI portal filter: xml_status='parsed' CFDIs show even with total=0."""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

if not os.environ.get("APP_DB_PATH"):
    _fd, _p = tempfile.mkstemp(suffix=".db", prefix="test_cfdi_filter_")
    os.close(_fd)
    os.environ["APP_DB_PATH"] = _p
if not os.environ.get("SESSION_SECRET"):
    os.environ["SESSION_SECRET"] = "test-secret-cfdi-filter"

import pytest
from fastapi.testclient import TestClient

from app import app
from config import DB_PATH
from database import db
from migrations_runner import apply_migrations
from tests.helpers import make_session_cookie

ISSUER_ID = 8870
USER_ID = 8870


def _ym_today() -> str:
    from datetime import date
    t = date.today()
    return f"{t.year:04d}-{t.month:02d}"


YM = _ym_today()


@pytest.fixture(scope="module", autouse=True)
def seed():
    """Create issuer, user, membership, and test CFDIs."""
    apply_migrations(DB_PATH)
    conn = db()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO issuers (id, rfc, razon_social, active, created_at, updated_at) "
            "VALUES (?, 'XAXX010101000', 'Filtro Test SA', 1, datetime('now'), datetime('now'))",
            (ISSUER_ID,),
        )
        conn.execute(
            "INSERT OR IGNORE INTO users (id, email, password_hash, created_at) "
            "VALUES (?, 'filter@test.local', 'x', datetime('now'))",
            (USER_ID,),
        )
        conn.execute(
            "INSERT OR IGNORE INTO memberships (user_id, issuer_id, role, created_at) "
            "VALUES (?, ?, 'owner', datetime('now'))",
            (USER_ID, ISSUER_ID),
        )
        # Clean stale test data (dates may have changed)
        conn.execute("DELETE FROM sat_cfdi WHERE issuer_id = ?", (ISSUER_ID,))
        # CFDI 1: parsed XML, total=0 — should SHOW
        conn.execute(
            "INSERT OR IGNORE INTO sat_cfdi "
            "(issuer_id, direction, uuid, fecha_emision, total, xml_status, status, rfc_receptor, nombre_receptor, concepto) "
            "VALUES (?, 'issued', 'parsed-zero-total-001', ?, 0.0, 'parsed', '1', 'XAXX010101000', 'Test', 'Nota de crédito')",
            (ISSUER_ID, f"{YM}-15T12:00:00"),
        )
        # CFDI 2: no XML (metadata-only), total=0 — should HIDE
        conn.execute(
            "INSERT OR IGNORE INTO sat_cfdi "
            "(issuer_id, direction, uuid, fecha_emision, total, xml_status, status, rfc_receptor, nombre_receptor, concepto) "
            "VALUES (?, 'issued', 'metadata-only-zero-002', ?, 0.0, NULL, '1', 'XAXX010101000', 'Test', 'Pendiente')",
            (ISSUER_ID, f"{YM}-16T12:00:00"),
        )
        # CFDI 3: no XML, but real total (>0.01) — should SHOW
        conn.execute(
            "INSERT OR IGNORE INTO sat_cfdi "
            "(issuer_id, direction, uuid, fecha_emision, total, xml_status, status, rfc_receptor, nombre_receptor, concepto) "
            "VALUES (?, 'issued', 'no-xml-real-total-003', ?, 5000.0, NULL, '1', 'XAXX010101000', 'Test', 'Factura normal')",
            (ISSUER_ID, f"{YM}-17T12:00:00"),
        )
        conn.commit()
    finally:
        conn.close()
    yield


@pytest.fixture(scope="module")
def client():
    cookies = make_session_cookie(issuer_id=ISSUER_ID, user_id=USER_ID)
    return TestClient(app, raise_server_exceptions=False, cookies=cookies)


def _get_uuids(client, ym=YM):
    r = client.get(f"/api/invoices/issued?ym={ym}")
    assert r.status_code == 200
    return [d["uuid"] for d in r.json()["data"]]


def test_should_show_parsed_cfdi_even_when_total_zero(client):
    """A CFDI with xml_status='parsed' and total=0 must appear in the list."""
    uuids = _get_uuids(client)
    assert "parsed-zero-total-001" in uuids


def test_should_hide_cfdi_with_no_xml_and_zero_total(client):
    """A metadata-only CFDI (no XML, total=0) must NOT appear — no noise for user."""
    uuids = _get_uuids(client)
    assert "metadata-only-zero-002" not in uuids


def test_should_show_cfdi_with_real_total_even_without_xml_parsed(client):
    """A CFDI without parsed XML but with real total (>0.01) still appears."""
    uuids = _get_uuids(client)
    assert "no-xml-real-total-003" in uuids
