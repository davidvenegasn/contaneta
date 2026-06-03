"""Tests for catch-up script for pre-wizard issuers."""

import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

if not os.environ.get("APP_DB_PATH"):
    _fd, _p = tempfile.mkstemp(suffix=".db", prefix="test_catch_up_")
    os.close(_fd)
    os.environ["APP_DB_PATH"] = _p
if not os.environ.get("SESSION_SECRET"):
    os.environ["SESSION_SECRET"] = "test-secret-catch-up"

import database  # noqa: E402
from config import DB_PATH  # noqa: E402
from migrations_runner import apply_migrations  # noqa: E402

sys.path.insert(0, str(ROOT / "scripts"))

PRE_WIZARD_ISSUER = 90400
POST_WIZARD_ISSUER = 90401


@pytest.fixture(scope="module", autouse=True)
def setup_db():
    apply_migrations(DB_PATH)
    conn = database.db()
    try:
        # Pre-wizard issuer (FIEL before 2026-06-01)
        conn.execute(
            "INSERT OR IGNORE INTO issuers (id, rfc, razon_social, active, created_at, updated_at) "
            "VALUES (?, 'PRE010101AAA', 'Pre Wizard SA', 1, datetime('now'), datetime('now'))",
            (PRE_WIZARD_ISSUER,),
        )
        conn.execute("DELETE FROM sat_credentials WHERE issuer_id = ?", (PRE_WIZARD_ISSUER,))
        conn.execute(
            "INSERT INTO sat_credentials (issuer_id, fiel_cer_path, fiel_key_path, fiel_key_password, validation_ok, created_at, updated_at) "
            "VALUES (?, '/tmp/test.cer', '/tmp/test.key', 'testpass', 1, '2026-05-15T10:00:00Z', datetime('now'))",
            (PRE_WIZARD_ISSUER,),
        )
        # Post-wizard issuer (FIEL after 2026-06-01)
        conn.execute(
            "INSERT OR IGNORE INTO issuers (id, rfc, razon_social, active, created_at, updated_at) "
            "VALUES (?, 'POST010101AAA', 'Post Wizard SA', 1, datetime('now'), datetime('now'))",
            (POST_WIZARD_ISSUER,),
        )
        conn.execute("DELETE FROM sat_credentials WHERE issuer_id = ?", (POST_WIZARD_ISSUER,))
        conn.execute(
            "INSERT INTO sat_credentials (issuer_id, fiel_cer_path, fiel_key_path, fiel_key_password, validation_ok, created_at, updated_at) "
            "VALUES (?, '/tmp/test.cer', '/tmp/test.key', 'testpass', 1, '2026-06-10T10:00:00Z', datetime('now'))",
            (POST_WIZARD_ISSUER,),
        )
        # Clean catch-up table for test issuer
        conn.execute("DELETE FROM issuer_catch_up_done WHERE issuer_id = ?", (PRE_WIZARD_ISSUER,))
        # Clean stale sat_jobs to avoid rate limit
        conn.execute(
            "UPDATE sat_jobs SET status = 'ok', created_at = datetime('now', '-2 hours') "
            "WHERE status = 'queued'"
        )
        conn.commit()
    finally:
        conn.close()
    yield


def test_find_pending_returns_only_pre_wizard_issuers():
    """Only issuers with FIEL before 2026-06-01 should be pending."""
    from scripts.catch_up_existing_issuers import find_pending
    pending = find_pending()
    assert PRE_WIZARD_ISSUER in pending
    assert POST_WIZARD_ISSUER not in pending


def test_dry_run_does_not_modify():
    """Dry run should not create sat_jobs or mark issuer as done."""
    from scripts.catch_up_existing_issuers import catch_up_one, find_pending
    n = catch_up_one(PRE_WIZARD_ISSUER, dry_run=True)
    assert n > 0
    # Should still be pending
    pending = find_pending()
    assert PRE_WIZARD_ISSUER in pending


def test_catch_up_marks_issuer_done():
    """After real catch-up, issuer should be marked as done."""
    from scripts.catch_up_existing_issuers import catch_up_one, find_pending
    # Clean sat_jobs first to avoid rate limit
    conn = database.db()
    try:
        conn.execute("DELETE FROM sat_jobs WHERE issuer_id = ?", (PRE_WIZARD_ISSUER,))
        conn.execute(
            "UPDATE sat_jobs SET status = 'ok', created_at = datetime('now', '-2 hours') "
            "WHERE status = 'queued'"
        )
        conn.commit()
    finally:
        conn.close()

    n = catch_up_one(PRE_WIZARD_ISSUER, dry_run=False)
    assert n > 0
    # Should no longer be pending
    pending = find_pending()
    assert PRE_WIZARD_ISSUER not in pending


def test_catch_up_skips_already_done():
    """Issuer already caught up should not appear in pending."""
    from scripts.catch_up_existing_issuers import find_pending
    pending = find_pending()
    assert PRE_WIZARD_ISSUER not in pending
