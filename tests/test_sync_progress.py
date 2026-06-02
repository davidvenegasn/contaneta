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


def test_sync_progress_excludes_stale_queued_jobs(client):
    """Queued sat_jobs older than 2h must not count as active."""
    conn = db()
    try:
        conn.execute("DELETE FROM sat_jobs WHERE issuer_id = ?", (ISSUER_ID,))
        # Insert a stale queued job (3 hours old)
        conn.execute(
            "INSERT INTO sat_jobs (issuer_id, job_type, direction, status, created_at, updated_at) "
            "VALUES (?, 'xml', 'issued', 'queued', datetime('now', '-3 hours'), datetime('now', '-3 hours'))",
            (ISSUER_ID,),
        )
        # Insert a fresh queued job (5 min old)
        conn.execute(
            "INSERT INTO sat_jobs (issuer_id, job_type, direction, status, created_at, updated_at) "
            "VALUES (?, 'xml', 'received', 'queued', datetime('now', '-5 minutes'), datetime('now', '-5 minutes'))",
            (ISSUER_ID,),
        )
        conn.commit()
    finally:
        conn.close()

    resp = client.get("/api/sync/progress")
    assert resp.status_code == 200
    data = resp.json()["data"]
    # Only the fresh job should count as active
    assert data["active"] == 1
    assert data["syncing"] is True


def test_sync_progress_returns_false_when_only_stale_jobs_exist(client):
    """syncing=false when all queued/running jobs are stale (>2h old)."""
    conn = db()
    try:
        conn.execute("DELETE FROM sat_jobs WHERE issuer_id = ?", (ISSUER_ID,))
        conn.execute("DELETE FROM jobs WHERE issuer_id = ?", (ISSUER_ID,))
        # Only stale jobs
        conn.execute(
            "INSERT INTO sat_jobs (issuer_id, job_type, direction, status, created_at, updated_at) "
            "VALUES (?, 'xml', 'issued', 'queued', datetime('now', '-5 hours'), datetime('now', '-5 hours'))",
            (ISSUER_ID,),
        )
        conn.execute(
            "INSERT INTO sat_jobs (issuer_id, job_type, direction, status, created_at, updated_at) "
            "VALUES (?, 'xml', 'received', 'running', datetime('now', '-4 hours'), datetime('now', '-4 hours'))",
            (ISSUER_ID,),
        )
        conn.commit()
    finally:
        conn.close()

    resp = client.get("/api/sync/progress")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["syncing"] is False
    assert data["active"] == 0


def test_expire_stale_marks_old_queued_as_expired():
    """expire_queued() should mark old queued jobs as expired."""
    conn = db()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO issuers (id, rfc, razon_social, active, created_at, updated_at) "
            "VALUES (99900, 'EXP990101AAA', 'Expire Test', 1, datetime('now'), datetime('now'))"
        )
        conn.execute("DELETE FROM sat_jobs WHERE issuer_id = 99900")
        conn.execute(
            "INSERT INTO sat_jobs (issuer_id, job_type, direction, status, created_at, updated_at) "
            "VALUES (99900, 'xml', 'issued', 'queued', datetime('now', '-5 hours'), datetime('now', '-5 hours'))"
        )
        conn.commit()
    finally:
        conn.close()

    from scripts.expire_stale_sat_jobs import expire_queued
    result = expire_queued(max_age_hours=2, dry_run=False)
    assert result["total"] >= 1

    conn = db()
    try:
        row = conn.execute(
            "SELECT status FROM sat_jobs WHERE issuer_id = 99900 ORDER BY id DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()
    assert row["status"] == "error"


def test_expire_stale_dry_run_does_not_modify():
    """expire_queued(dry_run=True) should report but not change status."""
    conn = db()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO issuers (id, rfc, razon_social, active, created_at, updated_at) "
            "VALUES (99901, 'DRY990101AAA', 'DryRun Test', 1, datetime('now'), datetime('now'))"
        )
        conn.execute("DELETE FROM sat_jobs WHERE issuer_id = 99901")
        conn.execute(
            "INSERT INTO sat_jobs (issuer_id, job_type, direction, status, created_at, updated_at) "
            "VALUES (99901, 'xml', 'issued', 'queued', datetime('now', '-5 hours'), datetime('now', '-5 hours'))"
        )
        conn.commit()
    finally:
        conn.close()

    from scripts.expire_stale_sat_jobs import expire_queued
    result = expire_queued(max_age_hours=2, dry_run=True)
    assert result["total"] >= 1

    conn = db()
    try:
        row = conn.execute(
            "SELECT status FROM sat_jobs WHERE issuer_id = 99901 ORDER BY id DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()
    # Should still be queued (dry run didn't change it)
    assert row["status"] == "queued"
