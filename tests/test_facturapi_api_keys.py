"""Tests for per-org Facturapi API key persistence (encrypted at rest)."""
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_test_db = os.environ.get("APP_DB_PATH")
if not _test_db:
    _fd, _test_db = tempfile.mkstemp(suffix=".db", prefix="test_fpi_apikeys_")
    os.close(_fd)
    os.environ["APP_DB_PATH"] = _test_db
if not os.environ.get("SESSION_SECRET"):
    os.environ["SESSION_SECRET"] = "test-secret-fpi-apikeys"
os.environ.setdefault("FACTURAPI_SECRET_KEY", "sk_test_FAKE_FOR_UNIT_TESTS")

import database  # noqa: E402
from config import DB_PATH  # noqa: E402
from migrations_runner import apply_migrations  # noqa: E402

ISSUER_ID = 91000


@pytest.fixture(scope="module", autouse=True)
def setup_db():
    apply_migrations(DB_PATH)
    conn = database.db()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO issuers (id, rfc, razon_social, active, created_at, updated_at) "
            "VALUES (?, 'KEY010101AAA', 'API Keys SA', 1, datetime('now'), datetime('now'))",
            (ISSUER_ID,),
        )
        conn.commit()
    finally:
        conn.close()
    yield


def test_save_and_load_roundtrip():
    """Saving a test key and loading it back should return the original value."""
    from services.facturapi.api_keys import save_org_keys, load_org_key

    save_org_keys(ISSUER_ID, test_key="sk_test_abc123xyz")
    loaded = load_org_key(ISSUER_ID, mode="test")
    assert loaded == "sk_test_abc123xyz"


def test_saved_key_is_encrypted_in_db():
    """The stored value in DB should be encrypted (prefixed with enc:), not plaintext."""
    from services.facturapi.api_keys import save_org_keys

    save_org_keys(ISSUER_ID, test_key="sk_test_plaincheck")
    conn = database.db()
    try:
        row = conn.execute(
            "SELECT facturapi_test_key_encrypted FROM issuers WHERE id = ?",
            (ISSUER_ID,),
        ).fetchone()
    finally:
        conn.close()
    enc = row["facturapi_test_key_encrypted"]
    assert enc is not None
    assert enc.startswith("enc:")
    assert "sk_test_plaincheck" not in enc


def test_load_returns_none_when_not_set():
    """Loading a key for an issuer that hasn't saved one should return None."""
    from services.facturapi.api_keys import load_org_key

    result = load_org_key(99999, mode="test")
    assert result is None


def test_save_live_key():
    """Saving and loading a live key should work independently of test key."""
    from services.facturapi.api_keys import save_org_keys, load_org_key

    save_org_keys(ISSUER_ID, live_key="sk_live_abc456")
    loaded = load_org_key(ISSUER_ID, mode="live")
    assert loaded == "sk_live_abc456"


def test_keys_fetched_at_set():
    """Saving keys should set facturapi_keys_fetched_at timestamp."""
    from services.facturapi.api_keys import save_org_keys

    save_org_keys(ISSUER_ID, test_key="sk_test_ts_check")
    conn = database.db()
    try:
        row = conn.execute(
            "SELECT facturapi_keys_fetched_at FROM issuers WHERE id = ?",
            (ISSUER_ID,),
        ).fetchone()
    finally:
        conn.close()
    assert row["facturapi_keys_fetched_at"] is not None
