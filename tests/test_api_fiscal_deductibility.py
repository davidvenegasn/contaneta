"""Tests for POST /api/cfdi/{uuid}/deductibility."""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_test_db = os.environ.get("APP_DB_PATH")
if not _test_db:
    _fd, _test_db = tempfile.mkstemp(suffix=".db", prefix="test_api_fiscal_")
    os.close(_fd)
    os.environ["APP_DB_PATH"] = _test_db
if not os.environ.get("SESSION_SECRET"):
    os.environ["SESSION_SECRET"] = "test-secret-fiscal-deduct"

from fastapi.testclient import TestClient  # noqa: E402

from app import app  # noqa: E402
from config import DB_PATH  # noqa: E402
from database import db  # noqa: E402
from migrations_runner import apply_migrations  # noqa: E402
from tests.helpers import make_session_cookie  # noqa: E402

ISSUER_A = 8801
USER_A = 8801
ISSUER_B = 8802
USER_B = 8802
CFDI_UUID = "AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE"


def _seed():
    apply_migrations(DB_PATH)
    conn = db()
    try:
        for uid, iid, email in [(USER_A, ISSUER_A, "fiscal_a@test.local"), (USER_B, ISSUER_B, "fiscal_b@test.local")]:
            conn.execute(
                "INSERT OR IGNORE INTO issuers (id, rfc, razon_social, active, created_at, updated_at) "
                "VALUES (?, 'RFC' || ?, 'Issuer ' || ?, 1, datetime('now'), datetime('now'))",
                (iid, str(iid), str(iid)),
            )
            conn.execute(
                "INSERT OR IGNORE INTO users (id, email, password_hash, created_at) VALUES (?, ?, 'x', datetime('now'))",
                (uid, email),
            )
            conn.execute(
                "INSERT OR IGNORE INTO memberships (user_id, issuer_id, role, created_at) VALUES (?, ?, 'owner', datetime('now'))",
                (uid, iid),
            )
        # CFDI belonging to ISSUER_A
        conn.execute(
            "INSERT OR IGNORE INTO sat_cfdi (issuer_id, uuid, direction, status, fecha_emision, "
            "rfc_emisor, nombre_emisor, rfc_receptor, nombre_receptor, total, moneda, created_at, updated_at) "
            "VALUES (?, ?, 'received', 'vigente', '2026-03-01', 'XAXX010101000', 'Proveedor', "
            "'RFC8801', 'Issuer 8801', 1000.0, 'MXN', datetime('now'), datetime('now'))",
            (ISSUER_A, CFDI_UUID),
        )
        conn.commit()
    finally:
        conn.close()


def test_should_set_deductibility_success():
    _seed()
    c = TestClient(app)
    c.cookies.update(make_session_cookie(ISSUER_A, USER_A))
    r = c.post(f"/api/cfdi/{CFDI_UUID}/deductibility", json={"percentage": 50.0})
    assert r.status_code == 200
    j = r.json()
    assert j["ok"] is True
    assert j["data"]["percentage"] == 50.0
    assert j["data"]["source"] == "manual"


def test_should_persist_deductibility():
    _seed()
    c = TestClient(app)
    c.cookies.update(make_session_cookie(ISSUER_A, USER_A))
    c.post(f"/api/cfdi/{CFDI_UUID}/deductibility", json={"percentage": 8.5})
    # Verify via service
    from services.fiscal.deductibility import get_deductibility
    result = get_deductibility(ISSUER_A, CFDI_UUID)
    assert result["percentage"] == 8.5
    assert result["source"] == "manual"


def test_should_reject_invalid_percentage():
    _seed()
    c = TestClient(app)
    c.cookies.update(make_session_cookie(ISSUER_A, USER_A))
    r = c.post(f"/api/cfdi/{CFDI_UUID}/deductibility", json={"percentage": -10.0})
    assert r.status_code == 400

    r = c.post(f"/api/cfdi/{CFDI_UUID}/deductibility", json={"percentage": 110.0})
    assert r.status_code == 400


def test_should_return_404_for_missing_cfdi():
    _seed()
    c = TestClient(app)
    c.cookies.update(make_session_cookie(ISSUER_A, USER_A))
    r = c.post("/api/cfdi/NONEXISTENT-UUID/deductibility", json={"percentage": 50.0})
    assert r.status_code == 404


def test_should_return_404_for_cross_tenant():
    """User B cannot set deductibility on User A's CFDI."""
    _seed()
    c = TestClient(app)
    c.cookies.update(make_session_cookie(ISSUER_B, USER_B))
    r = c.post(f"/api/cfdi/{CFDI_UUID}/deductibility", json={"percentage": 50.0})
    assert r.status_code == 404
