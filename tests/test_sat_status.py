"""Tests for SAT connection status service and API endpoint."""

import os
import sys
import tempfile
from pathlib import Path

import pytest

# Fix DB path before importing app/config
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_test_db = os.environ.get("APP_DB_PATH")
if not _test_db:
    _fd, _test_db = tempfile.mkstemp(suffix=".db", prefix="test_sat_status_")
    os.close(_fd)
    os.environ["APP_DB_PATH"] = _test_db
if not os.environ.get("SESSION_SECRET"):
    os.environ["SESSION_SECRET"] = "test-secret-sat-status"

from fastapi.testclient import TestClient  # noqa: E402

from config import DB_PATH  # noqa: E402
from database import db, has_column  # noqa: E402
from migrations_runner import apply_migrations  # noqa: E402
from tests.helpers import make_session_cookie  # noqa: E402

from app import app  # noqa: E402


# High IDs to avoid collisions with other test files
ISSUER_SAT = 201
ISSUER_NO_SAT = 202
USER_SAT = 201
USER_NO_SAT = 202


def _ensure_validation_columns(conn):
    """Ensure sat_credentials has validation_* columns for tests."""
    for col, col_type in [
        ("validation_at", "TEXT"),
        ("validation_ok", "INTEGER"),
        ("validation_message", "TEXT"),
    ]:
        if not has_column(conn, "sat_credentials", col):
            conn.execute(
                f"ALTER TABLE sat_credentials ADD COLUMN {col} {col_type};"
            )


def _seed_test_data():
    """Create test issuers, users, memberships, and SAT data."""
    apply_migrations(DB_PATH)
    conn = db()
    try:
        # Clean our fixtures
        conn.execute(
            "DELETE FROM sat_jobs WHERE issuer_id IN (?, ?)",
            (ISSUER_SAT, ISSUER_NO_SAT),
        )
        conn.execute(
            "DELETE FROM sat_cfdi WHERE issuer_id IN (?, ?)",
            (ISSUER_SAT, ISSUER_NO_SAT),
        )
        conn.execute(
            "DELETE FROM sat_sync_state WHERE issuer_id IN (?, ?)",
            (ISSUER_SAT, ISSUER_NO_SAT),
        )
        conn.execute(
            "DELETE FROM sat_credentials WHERE issuer_id IN (?, ?)",
            (ISSUER_SAT, ISSUER_NO_SAT),
        )
        conn.execute(
            "DELETE FROM memberships WHERE user_id IN (?, ?) OR issuer_id IN (?, ?)",
            (USER_SAT, USER_NO_SAT, ISSUER_SAT, ISSUER_NO_SAT),
        )

        # Issuers
        conn.execute(
            "INSERT OR IGNORE INTO issuers (id, rfc, razon_social, active, created_at, updated_at) "
            "VALUES (?, 'SAT201RFC', 'Issuer SAT', 1, datetime('now'), datetime('now'))",
            (ISSUER_SAT,),
        )
        conn.execute(
            "INSERT OR IGNORE INTO issuers (id, rfc, razon_social, active, created_at, updated_at) "
            "VALUES (?, 'NOSAT202RFC', 'Issuer No SAT', 1, datetime('now'), datetime('now'))",
            (ISSUER_NO_SAT,),
        )

        # Users
        conn.execute(
            "INSERT OR IGNORE INTO users (id, email, password_hash, created_at) "
            "VALUES (?, 'sat201@test.local', '$2b$12$x', datetime('now'))",
            (USER_SAT,),
        )
        conn.execute(
            "INSERT OR IGNORE INTO users (id, email, password_hash, created_at) "
            "VALUES (?, 'nosat202@test.local', '$2b$12$x', datetime('now'))",
            (USER_NO_SAT,),
        )

        # Memberships
        conn.execute(
            "INSERT INTO memberships (user_id, issuer_id, role, created_at) "
            "VALUES (?, ?, 'owner', datetime('now'))",
            (USER_SAT, ISSUER_SAT),
        )
        conn.execute(
            "INSERT INTO memberships (user_id, issuer_id, role, created_at) "
            "VALUES (?, ?, 'owner', datetime('now'))",
            (USER_NO_SAT, ISSUER_NO_SAT),
        )

        # SAT credentials for ISSUER_SAT (with validation columns)
        _ensure_validation_columns(conn)
        conn.execute(
            "INSERT INTO sat_credentials "
            "(issuer_id, fiel_cer_path, fiel_key_path, fiel_key_password, "
            "validation_ok, validation_at, validation_message, created_at, updated_at) "
            "VALUES (?, 'fake/cer.cer.enc', 'fake/key.key.enc', 'enc:fakepwd', "
            "1, '2026-05-10 12:00:00', 'FIEL validada correctamente.', datetime('now'), datetime('now'))",
            (ISSUER_SAT,),
        )

        # SAT jobs for ISSUER_SAT
        conn.execute(
            "INSERT INTO sat_jobs (issuer_id, job_type, direction, status, started_at, finished_at, created_at, updated_at) "
            "VALUES (?, 'metadata', 'issued', 'ok', '2026-05-10 10:00:00', '2026-05-10 10:05:00', '2026-05-10 10:00:00', '2026-05-10 10:05:00')",
            (ISSUER_SAT,),
        )
        conn.execute(
            "INSERT INTO sat_jobs (issuer_id, job_type, direction, status, started_at, finished_at, created_at, updated_at) "
            "VALUES (?, 'xml', 'received', 'ok', '2026-05-10 11:00:00', '2026-05-10 11:15:00', '2026-05-10 11:00:00', '2026-05-10 11:15:00')",
            (ISSUER_SAT,),
        )
        conn.execute(
            "INSERT INTO sat_jobs (issuer_id, job_type, direction, status, started_at, finished_at, last_error, created_at, updated_at) "
            "VALUES (?, 'metadata', 'received', 'error', '2026-05-09 08:00:00', '2026-05-09 08:01:00', 'Timeout al conectar', '2026-05-09 08:00:00', '2026-05-09 08:01:00')",
            (ISSUER_SAT,),
        )

        # SAT sync state
        conn.execute(
            "INSERT OR REPLACE INTO sat_sync_state (issuer_id, direction, last_run_at) "
            "VALUES (?, 'issued', '2026-05-10 10:05:00')",
            (ISSUER_SAT,),
        )

        # SAT CFDI entries for ISSUER_SAT
        for i in range(5):
            conn.execute(
                "INSERT INTO sat_cfdi (issuer_id, direction, uuid, status, fecha_emision, total, created_at, updated_at) "
                "VALUES (?, 'issued', ?, 'vigente', '2026-05-01', 1000.0, datetime('now'), datetime('now'))",
                (ISSUER_SAT, f"uuid-sat-test-{i:03d}"),
            )

        conn.commit()
    finally:
        conn.close()


@pytest.fixture(scope="module")
def client():
    _seed_test_data()
    return TestClient(app)


# ─── Service: get_sat_connection_status ───


def test_should_return_not_connected_when_no_credentials(client):
    """Issuer without sat_credentials should show connected=False."""
    from services.sat_status import get_sat_connection_status

    status = get_sat_connection_status(ISSUER_NO_SAT)
    assert status["connected"] is False
    assert status["last_sync_at"] is None
    assert status["last_sync_status"] is None
    assert status["invoices_synced"] == 0


def test_should_return_connected_when_valid_credentials(client):
    """Issuer with valid sat_credentials and validation_ok=1 should show connected=True."""
    from services.sat_status import get_sat_connection_status

    status = get_sat_connection_status(ISSUER_SAT)
    assert status["connected"] is True
    assert status["invoices_synced"] == 5


def test_should_return_last_sync_info(client):
    """Issuer with sync history should report last sync timestamp and status."""
    from services.sat_status import get_sat_connection_status

    status = get_sat_connection_status(ISSUER_SAT)
    assert status["last_sync_at"] is not None
    # The latest successful job finished after the error job, so status should be success
    assert status["last_sync_status"] == "success"


def test_should_return_none_for_fiel_expiry(client):
    """FIEL expiry is not stored in current schema; should return None."""
    from services.sat_status import get_sat_connection_status

    status = get_sat_connection_status(ISSUER_SAT)
    assert status["fiel_expires_at"] is None
    assert status["fiel_days_remaining"] is None


# ─── Service: check_fiel_expiry_warning ───


def test_should_return_warning_when_no_credentials(client):
    """No FIEL credentials should produce an error-level warning."""
    from services.sat_status import check_fiel_expiry_warning

    warning = check_fiel_expiry_warning(ISSUER_NO_SAT)
    assert warning is not None
    assert warning["level"] == "error"
    assert "credenciales" in warning["message"].lower()


def test_should_return_no_warning_when_fiel_valid(client):
    """Valid FIEL should produce no warning."""
    from services.sat_status import check_fiel_expiry_warning

    warning = check_fiel_expiry_warning(ISSUER_SAT)
    assert warning is None


def test_should_return_error_when_fiel_validation_failed(client):
    """FIEL with validation_ok=0 should produce an error warning."""
    from services.sat_status import check_fiel_expiry_warning

    # Temporarily set validation_ok = 0
    conn = db()
    try:
        conn.execute(
            "UPDATE sat_credentials SET validation_ok = 0, validation_message = 'FIEL vencida' "
            "WHERE issuer_id = ?",
            (ISSUER_SAT,),
        )
        conn.commit()
    finally:
        conn.close()

    warning = check_fiel_expiry_warning(ISSUER_SAT)
    assert warning is not None
    assert warning["level"] == "error"
    assert "vencida" in warning["message"].lower()

    # Restore
    conn = db()
    try:
        conn.execute(
            "UPDATE sat_credentials SET validation_ok = 1, validation_message = 'FIEL validada correctamente.' "
            "WHERE issuer_id = ?",
            (ISSUER_SAT,),
        )
        conn.commit()
    finally:
        conn.close()


# ─── Service: get_sync_history ───


def test_should_return_sync_history(client):
    """Should return recent sync jobs ordered by creation date descending."""
    from services.sat_status import get_sync_history

    history = get_sync_history(ISSUER_SAT, limit=10)
    assert isinstance(history, list)
    assert len(history) == 3  # 2 ok + 1 error
    # Check required fields
    for row in history:
        assert "job_type" in row
        assert "status" in row
        assert row["status"] in ("ok", "error", "queued", "running")


def test_should_return_empty_history_when_no_jobs(client):
    """Issuer with no SAT jobs should return empty list."""
    from services.sat_status import get_sync_history

    history = get_sync_history(ISSUER_NO_SAT, limit=10)
    assert history == []


def test_should_respect_limit_parameter(client):
    """Limit parameter should cap the results."""
    from services.sat_status import get_sync_history

    history = get_sync_history(ISSUER_SAT, limit=1)
    assert len(history) == 1


# ─── API endpoint ───


def test_should_return_status_json_when_authenticated(client):
    """GET /portal/sat/status with valid session should return JSON status."""
    cookies = make_session_cookie(issuer_id=ISSUER_SAT, user_id=USER_SAT)
    resp = client.get("/portal/sat/status", cookies=cookies)
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    data = body["data"]
    assert "connected" in data
    assert "invoices_synced" in data
    assert "fiel_warning" in data
    assert "sync_history" in data
    assert data["connected"] is True
    assert data["invoices_synced"] == 5


def test_should_return_401_when_not_authenticated(client):
    """GET /portal/sat/status without session should return 401."""
    resp = client.get("/portal/sat/status")
    # Portal routes redirect to login on auth failure
    assert resp.status_code in (401, 302, 307)


def test_should_isolate_tenant_data(client):
    """Issuer B should not see issuer A SAT status data."""
    cookies = make_session_cookie(issuer_id=ISSUER_NO_SAT, user_id=USER_NO_SAT)
    resp = client.get("/portal/sat/status", cookies=cookies)
    assert resp.status_code == 200
    body = resp.json()
    data = body["data"]
    assert data["connected"] is False
    assert data["invoices_synced"] == 0
    assert data["sync_history"] == []


# ─── API /api/sat/status (operations.py) ───


def test_should_return_metadata_counts_in_api_sat_status(client):
    """GET /api/sat/status should include metadata_counts in response."""
    # Seed a metadata-only CFDI for ISSUER_SAT
    conn = db()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO sat_cfdi "
            "(issuer_id, direction, uuid, fecha_emision, total, xml_status, status) "
            "VALUES (?, 'issued', 'meta-only-status-test', '2026-05-15', 0.0, NULL, '1')",
            (ISSUER_SAT,),
        )
        conn.commit()
    finally:
        conn.close()

    cookies = make_session_cookie(issuer_id=ISSUER_SAT, user_id=USER_SAT)
    resp = client.get("/api/sat/status", cookies=cookies)
    assert resp.status_code == 200
    body = resp.json()
    data = body["data"]
    assert "metadata_counts" in data
    assert data["metadata_counts"].get("issued_metadata_only", 0) >= 1


def test_should_return_generic_jobs_in_api_sat_status(client):
    """GET /api/sat/status should include generic_jobs from jobs table."""
    cookies = make_session_cookie(issuer_id=ISSUER_SAT, user_id=USER_SAT)
    resp = client.get("/api/sat/status", cookies=cookies)
    assert resp.status_code == 200
    body = resp.json()
    data = body["data"]
    assert "generic_jobs" in data
    assert isinstance(data["generic_jobs"], list)


# ─── Full resync endpoint ───


def test_should_enqueue_full_resync_when_fiel_valid(client):
    """POST /portal/sat/full-resync should enqueue jobs for both directions."""
    cookies = make_session_cookie(issuer_id=ISSUER_SAT, user_id=USER_SAT)
    resp = client.post("/portal/sat/full-resync", cookies=cookies,
                       headers={"Accept": "application/json"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert "job_ids" in body
    assert len(body["job_ids"]) == 2


def test_should_reject_full_resync_without_valid_fiel(client):
    """POST /portal/sat/full-resync should fail if FIEL is not validated."""
    cookies = make_session_cookie(issuer_id=ISSUER_NO_SAT, user_id=USER_NO_SAT)
    resp = client.post("/portal/sat/full-resync", cookies=cookies,
                       headers={"Accept": "application/json"})
    assert resp.status_code == 400
