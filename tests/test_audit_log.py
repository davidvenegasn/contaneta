"""Tests for Audit Log UI (Phase 7): service + routes."""
import json

import pytest

from database import db
from services.action_log import get_audit_log, get_distinct_actions, log_action

ISSUER_ID = 99907
USER_ID = 99907


@pytest.fixture(scope="module", autouse=True)
def seed():
    """Create test data for audit log tests using the existing audit_log table."""
    conn = db()
    # Drop stale table and recreate with correct schema (migrations 007 + 011)
    conn.execute("DROP TABLE IF EXISTS audit_log")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS audit_log (
             id INTEGER PRIMARY KEY AUTOINCREMENT,
             created_at TEXT NOT NULL DEFAULT (datetime('now')),
             action TEXT NOT NULL,
             user_id INTEGER,
             issuer_id INTEGER,
             target_issuer_id INTEGER,
             details TEXT,
             entity TEXT,
             entity_id TEXT,
             meta_json TEXT,
             ip TEXT,
             user_agent TEXT
           )"""
    )
    conn.execute(
        """INSERT OR IGNORE INTO issuers (id, rfc, razon_social, active, regimen_fiscal)
           VALUES (?, 'XLOG010101AAA', 'Audit Test SA', 1, '601')""",
        (ISSUER_ID,),
    )
    conn.execute(
        """INSERT OR IGNORE INTO users (id, email, password_hash)
           VALUES (?, 'audit@test.com', 'x')""",
        (USER_ID,),
    )
    conn.execute(
        """INSERT OR IGNORE INTO memberships (user_id, issuer_id, role)
           VALUES (?, ?, 'owner')""",
        (USER_ID, ISSUER_ID),
    )
    # Seed some audit log entries
    for action, details, meta in [
        ("login", None, json.dumps({"source": "web"})),
        ("invoice_created", None, json.dumps({"invoice_id": 1, "uuid": "abc123"})),
        ("invoice_cancelled", None, json.dumps({"uuid": "abc123", "motive": "01"})),
        ("download_xml", None, None),
        ("credentials_uploaded", None, None),
    ]:
        conn.execute(
            """INSERT INTO audit_log (issuer_id, user_id, action, details, meta_json, ip)
               VALUES (?, ?, ?, ?, ?, '127.0.0.1')""",
            (ISSUER_ID, USER_ID, action, details, meta),
        )
    conn.commit()
    conn.close()
    yield


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from app import app
    from tests.helpers import make_session_cookie

    c = TestClient(app)
    cookies = make_session_cookie(ISSUER_ID, USER_ID)
    for k, v in cookies.items():
        c.cookies.set(k, v)
    return c


def test_should_return_all_entries():
    """get_audit_log should return all entries for the issuer."""
    rows, total = get_audit_log(ISSUER_ID)
    assert total >= 5
    assert len(rows) >= 5


def test_should_filter_by_action():
    """get_audit_log should filter by action type."""
    rows, total = get_audit_log(ISSUER_ID, action="login")
    assert total >= 1
    for r in rows:
        assert r["action"] == "login"


def test_should_filter_by_user_id():
    """get_audit_log should filter by user_id."""
    rows, total = get_audit_log(ISSUER_ID, user_id=USER_ID)
    assert total >= 5


def test_should_return_distinct_actions():
    """get_distinct_actions should return unique action types."""
    actions = get_distinct_actions(ISSUER_ID)
    assert "login" in actions
    assert "invoice_created" in actions


def test_should_paginate():
    """get_audit_log should respect limit and offset."""
    rows, total = get_audit_log(ISSUER_ID, limit=2, offset=0)
    assert len(rows) == 2
    assert total >= 5


def test_should_persist_from_log_action():
    """log_action should persist entries to the audit_log table."""
    conn = db()
    before = conn.execute(
        "SELECT COUNT(*) AS cnt FROM audit_log WHERE issuer_id = ?",
        (ISSUER_ID,),
    ).fetchone()["cnt"]
    conn.close()

    log_action(None, "test_action", issuer_id=ISSUER_ID, user_id=USER_ID, extra="data")

    conn = db()
    after = conn.execute(
        "SELECT COUNT(*) AS cnt FROM audit_log WHERE issuer_id = ?",
        (ISSUER_ID,),
    ).fetchone()["cnt"]
    conn.close()

    assert after == before + 1


def test_route_should_return_200_for_owner(client):
    """GET /portal/audit-log should return 200 for owner."""
    resp = client.get("/portal/audit-log")
    assert resp.status_code == 200
    assert "Registro de actividad" in resp.text


def test_route_should_filter_by_action(client):
    """GET /portal/audit-log?action=login should filter results."""
    resp = client.get("/portal/audit-log?action=login")
    assert resp.status_code == 200


def test_csv_export_should_return_csv(client):
    """GET /portal/audit-log/csv should return a CSV file."""
    resp = client.get("/portal/audit-log/csv")
    assert resp.status_code == 200
    assert "text/csv" in resp.headers.get("content-type", "")
    assert "Fecha" in resp.text
