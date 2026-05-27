import os
import sys
import tempfile
from pathlib import Path

# Fijar DB de test antes de importar app/config
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_test_db = os.environ.get("APP_DB_PATH")
if not _test_db:
    _fd, _test_db = tempfile.mkstemp(suffix=".db", prefix="test_health_")
    os.close(_fd)
    os.environ["APP_DB_PATH"] = _test_db
if not os.environ.get("SESSION_SECRET"):
    os.environ["SESSION_SECRET"] = "test-secret-health"

from fastapi.testclient import TestClient  # noqa: E402

from app import app  # noqa: E402


def test_health_json_shape():
    c = TestClient(app)
    r = c.get("/health")
    assert r.status_code == 200
    j = r.json()
    assert isinstance(j, dict)
    for k in (
        "status",
        "db",
        "db_readable",
        "migrations_applied",
        "migration_version",
        "storage_exists",
        "storage_writable",
        "disk_free_mb",
        "disk_ok",
        "stripe_configured",
    ):
        assert k in j, f"Missing key: {k}"
    assert isinstance(j["disk_ok"], bool)
    assert j["disk_free_mb"] is None or isinstance(j["disk_free_mb"], int)


def test_ready_json_shape():
    c = TestClient(app)
    r = c.get("/ready")
    assert r.status_code in (200, 503)
    j = r.json()
    assert isinstance(j, dict)
    assert "ready" in j
    if r.status_code == 200:
        assert j["ready"] is True
    else:
        assert j["ready"] is False
        assert j.get("reason") in (
            "db_not_readable",
            "migrations_not_applied",
            "storage_missing",
            "storage_not_writable",
            "unknown",
        )

