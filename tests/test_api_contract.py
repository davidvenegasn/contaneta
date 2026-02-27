import os
import sys
import tempfile
from pathlib import Path


# Fijar DB de test antes de importar app/config
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_test_db = os.environ.get("APP_DB_PATH")
if not _test_db:
    _fd, _test_db = tempfile.mkstemp(suffix=".db", prefix="test_api_contract_")
    os.close(_fd)
    os.environ["APP_DB_PATH"] = _test_db
if not os.environ.get("SESSION_SECRET"):
    os.environ["SESSION_SECRET"] = "test-secret-api-contract"

from fastapi.testclient import TestClient  # noqa: E402

from config import DB_PATH  # noqa: E402
from database import db  # noqa: E402
from migrations_runner import apply_migrations  # noqa: E402
from services import jobs as jobs_service  # noqa: E402
from tests.helpers import make_session_cookie  # noqa: E402
from app import app  # noqa: E402


ISSUER_ID = 9101
USER_ID = 9101


def _seed_min_auth():
    apply_migrations(DB_PATH)
    conn = db()
    try:
        # Limpiar nuestras fixtures
        conn.execute("DELETE FROM memberships WHERE user_id = ? OR issuer_id = ?", (USER_ID, ISSUER_ID))
        conn.execute("DELETE FROM users WHERE id = ?", (USER_ID,))
        conn.execute("DELETE FROM issuers WHERE id = ?", (ISSUER_ID,))

        # Issuer + user + membership
        conn.execute(
            "INSERT OR IGNORE INTO issuers (id, rfc, razon_social, active, created_at, updated_at) VALUES (?, 'TST9101', 'Issuer API Contract', 1, datetime('now'), datetime('now'))",
            (ISSUER_ID,),
        )
        conn.execute(
            "INSERT OR IGNORE INTO users (id, email, password_hash, created_at) VALUES (?, 'api_contract@test.local', 'x', datetime('now'))",
            (USER_ID,),
        )
        conn.execute(
            "INSERT OR IGNORE INTO memberships (user_id, issuer_id, role, created_at) VALUES (?, ?, 'owner', datetime('now'))",
            (USER_ID, ISSUER_ID),
        )
        conn.commit()
    finally:
        conn.close()


def test_ok_list_contract_for_core_lists():
    _seed_min_auth()
    c = TestClient(app)
    c.cookies.update(make_session_cookie(ISSUER_ID, USER_ID))

    for path in ("/api/jobs?limit=5", "/api/customers?limit=5&offset=0", "/api/products?limit=5&offset=0"):
        r = c.get(path)
        assert r.status_code == 200, (path, r.text)
        j = r.json()
        assert j.get("ok") is True
        assert "items" in j
        assert "data" in j
        assert isinstance(j["items"], list)
        assert isinstance(j["data"], dict)
        assert "items" in j["data"]
        assert isinstance(j["data"]["items"], list)
        assert "total" in j
        assert isinstance(j["total"], int)


def test_ok_contract_for_get_job():
    _seed_min_auth()
    job_id = jobs_service.run_job("contract_test", ISSUER_ID, payload={"a": 1})

    c = TestClient(app)
    c.cookies.update(make_session_cookie(ISSUER_ID, USER_ID))

    r = c.get(f"/api/jobs/{job_id}")
    assert r.status_code == 200
    j = r.json()
    assert j.get("ok") is True
    assert isinstance(j.get("data"), dict)
    assert j["data"].get("id") == job_id
    assert j["data"].get("issuer_id") == ISSUER_ID

