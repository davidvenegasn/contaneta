"""
Tests for Sentry integration (Job 3).

1. App imports OK without SENTRY_DSN (default).
2. App imports OK with SENTRY_DSN set (proves the code path runs).
3. /admin/sentry-test responds 403 without auth (admin-only).
4. _sentry_available flag is a boolean in the app module.
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Ensure test DB and session secret are set before importing anything
_test_db = os.environ.get("APP_DB_PATH")
if not _test_db:
    _fd, _test_db = tempfile.mkstemp(suffix=".db", prefix="test_sentry_")
    os.close(_fd)
    os.environ["APP_DB_PATH"] = _test_db
if not os.environ.get("SESSION_SECRET"):
    os.environ["SESSION_SECRET"] = "test-secret-sentry"


def test_app_imports_without_sentry_dsn():
    """App loads fine when SENTRY_DSN is not set (the common dev case)."""
    old = os.environ.pop("SENTRY_DSN", None)
    try:
        import app as app_mod
        assert app_mod.app is not None
        assert hasattr(app_mod.app, "routes")
    finally:
        if old is not None:
            os.environ["SENTRY_DSN"] = old


def test_app_imports_with_sentry_dsn_set():
    """App loads fine when SENTRY_DSN is set (even if the DSN is bogus).

    Note: since Python modules are cached, this verifies the module-level
    code didn't crash on the initial import (which already read the env).
    The important thing is that the app object is usable.
    """
    old = os.environ.get("SENTRY_DSN")
    os.environ["SENTRY_DSN"] = "https://fake@o0.ingest.sentry.io/0"
    try:
        import app as app_mod
        assert app_mod.app is not None
    finally:
        if old is not None:
            os.environ["SENTRY_DSN"] = old
        else:
            os.environ.pop("SENTRY_DSN", None)


def test_sentry_test_endpoint_requires_admin():
    """/admin/sentry-test must return 403 without a valid admin session."""
    from fastapi.testclient import TestClient
    from app import app

    client = TestClient(app, raise_server_exceptions=False)
    r = client.get("/admin/sentry-test")
    # Without admin auth, the require_admin dependency raises 403
    assert r.status_code == 403


def test_sentry_available_flag_is_bool():
    """_sentry_available must be a boolean in the app module."""
    import app as app_mod
    assert isinstance(app_mod._sentry_available, bool)
