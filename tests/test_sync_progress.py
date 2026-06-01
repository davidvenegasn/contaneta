"""Tests for sync progress banner endpoint."""

import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

if not os.environ.get("APP_DB_PATH"):
    _fd, _p = tempfile.mkstemp(suffix=".db", prefix="test_sync_progress_")
    os.close(_fd)
    os.environ["APP_DB_PATH"] = _p
if not os.environ.get("SESSION_SECRET"):
    os.environ["SESSION_SECRET"] = "test-secret-sync-progress"

from fastapi.testclient import TestClient  # noqa: E402

from app import app  # noqa: E402
from config import DB_PATH  # noqa: E402
from database import db  # noqa: E402
from migrations_runner import apply_migrations  # noqa: E402
from tests.helpers import make_session_cookie  # noqa: E402

ISSUER_ID = 8300
USER_ID = 8300


@pytest.fixture(scope="module", autouse=True)
def seed():
    apply_migrations(DB_PATH)
    conn = db()
    try:
        conn.execute(
            "INSERT INTO issuers (id, rfc, razon_social, active, created_at, updated_at) "
            "VALUES (?, 'PROG010101AAA', 'Progress Test SA', 1, datetime('now'), datetime('now')) "
            "ON CONFLICT(id) DO UPDATE SET rfc = excluded.rfc",
            (ISSUER_ID,),
        )
        conn.execute(
            "INSERT OR IGNORE INTO users (id, email, password_hash, created_at) "
            "VALUES (?, 'progress@test.local', 'x', datetime('now'))",
            (USER_ID,),
        )
        conn.execute(
            "INSERT OR IGNORE INTO memberships (user_id, issuer_id, role, created_at) "
            "VALUES (?, ?, 'owner', datetime('now'))",
            (USER_ID, ISSUER_ID),
        )
        # Clean previous test data
        conn.execute("DELETE FROM sat_jobs WHERE issuer_id = ?", (ISSUER_ID,))
        conn.execute("DELETE FROM jobs WHERE issuer_id = ?", (ISSUER_ID,))
        conn.commit()
    finally:
        conn.close()
    yield


@pytest.fixture(scope="module")
def client():
    cookies = make_session_cookie(issuer_id=ISSUER_ID, user_id=USER_ID)
    return TestClient(app, raise_server_exceptions=False, cookies=cookies)


def test_should_return_not_syncing_when_no_jobs(client):
    """GET /api/sync/progress returns syncing=false with no active jobs."""
    resp = client.get("/api/sync/progress")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["syncing"] is False
    assert data["active"] == 0


def test_should_return_syncing_when_jobs_running(client):
    """GET /api/sync/progress returns syncing=true when sat_jobs are running."""
    conn = db()
    try:
        conn.execute(
            "INSERT INTO sat_jobs (issuer_id, job_type, direction, status, created_at, updated_at) "
            "VALUES (?, 'xml', 'issued', 'running', datetime('now'), datetime('now'))",
            (ISSUER_ID,),
        )
        conn.execute(
            "INSERT INTO sat_jobs (issuer_id, job_type, direction, status, created_at, updated_at) "
            "VALUES (?, 'xml', 'received', 'queued', datetime('now'), datetime('now'))",
            (ISSUER_ID,),
        )
        conn.commit()
    finally:
        conn.close()

    resp = client.get("/api/sync/progress")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["syncing"] is True
    assert data["active"] >= 2


def test_should_count_done_jobs(client):
    """GET /api/sync/progress counts completed jobs."""
    conn = db()
    try:
        conn.execute(
            "INSERT INTO sat_jobs (issuer_id, job_type, direction, status, created_at, updated_at) "
            "VALUES (?, 'xml', 'issued', 'ok', datetime('now'), datetime('now'))",
            (ISSUER_ID,),
        )
        conn.commit()
    finally:
        conn.close()

    resp = client.get("/api/sync/progress")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["done"] >= 1
    assert data["total"] >= 3


def test_should_return_401_without_session(client):
    """GET /api/sync/progress without auth returns 401 or redirect."""
    plain_client = TestClient(app, raise_server_exceptions=False)
    resp = plain_client.get("/api/sync/progress")
    assert resp.status_code in (401, 302, 307)
