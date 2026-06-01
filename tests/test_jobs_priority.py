"""Tests for job queue priority ordering."""

import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

if not os.environ.get("APP_DB_PATH"):
    _fd, _p = tempfile.mkstemp(suffix=".db", prefix="test_jobs_priority_")
    os.close(_fd)
    os.environ["APP_DB_PATH"] = _p
if not os.environ.get("SESSION_SECRET"):
    os.environ["SESSION_SECRET"] = "test-secret-jobs-priority"

from config import DB_PATH  # noqa: E402
from database import db  # noqa: E402
from migrations_runner import apply_migrations  # noqa: E402
from services.jobs import claim_next_job, complete_job, enqueue_job  # noqa: E402

ISSUER_ID = 8200


@pytest.fixture(scope="module", autouse=True)
def seed():
    apply_migrations(DB_PATH)
    conn = db()
    try:
        conn.execute(
            "INSERT INTO issuers (id, rfc, razon_social, active, created_at, updated_at) "
            "VALUES (?, 'PRIO010101AAA', 'Priority Test SA', 1, datetime('now'), datetime('now')) "
            "ON CONFLICT(id) DO UPDATE SET rfc = excluded.rfc",
            (ISSUER_ID,),
        )
        conn.commit()
    finally:
        conn.close()
    yield
    # Clean up test jobs
    conn = db()
    try:
        conn.execute("DELETE FROM jobs WHERE issuer_id = ?", (ISSUER_ID,))
        conn.commit()
    finally:
        conn.close()


def _clean_jobs():
    """Remove all test jobs before each test."""
    conn = db()
    try:
        conn.execute("DELETE FROM jobs WHERE issuer_id = ?", (ISSUER_ID,))
        conn.commit()
    finally:
        conn.close()


def test_should_enqueue_job_with_priority():
    """enqueue_job should store priority value."""
    _clean_jobs()
    jid = enqueue_job("test_prio", ISSUER_ID, {"k": "v1"}, priority=5)
    conn = db()
    try:
        row = conn.execute("SELECT priority FROM jobs WHERE id = ?", (jid,)).fetchone()
        assert row is not None
        assert row["priority"] == 5
    finally:
        conn.close()


def test_should_claim_high_priority_first():
    """Worker should pick higher priority jobs before lower ones."""
    _clean_jobs()
    # Enqueue low priority first (created earlier)
    low_id = enqueue_job("test_low", ISSUER_ID, {"order": "low"}, priority=0)
    # Enqueue high priority second (created later)
    high_id = enqueue_job("test_high", ISSUER_ID, {"order": "high"}, priority=10)

    # Claim should pick the high-priority job first
    job = claim_next_job("test-worker")
    assert job is not None
    assert job["id"] == high_id
    complete_job(high_id)

    # Next claim should pick the low-priority job
    job2 = claim_next_job("test-worker")
    assert job2 is not None
    assert job2["id"] == low_id
    complete_job(low_id)


def test_should_use_fifo_within_same_priority():
    """Jobs with the same priority should be FIFO (oldest first)."""
    _clean_jobs()
    id1 = enqueue_job("test_same_a", ISSUER_ID, {"seq": 1}, priority=5)
    id2 = enqueue_job("test_same_b", ISSUER_ID, {"seq": 2}, priority=5)

    job = claim_next_job("test-worker")
    assert job is not None
    assert job["id"] == id1  # First created, same priority → picked first
    complete_job(id1)

    job2 = claim_next_job("test-worker")
    assert job2 is not None
    assert job2["id"] == id2
    complete_job(id2)


def test_should_default_priority_to_zero():
    """Jobs without explicit priority should default to 0."""
    _clean_jobs()
    jid = enqueue_job("test_default_prio", ISSUER_ID, {"k": "default"})
    conn = db()
    try:
        row = conn.execute("SELECT priority FROM jobs WHERE id = ?", (jid,)).fetchone()
        assert row is not None
        assert row["priority"] == 0
    finally:
        conn.close()
