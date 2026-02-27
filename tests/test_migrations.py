import os
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_test_db = os.environ.get("APP_DB_PATH")
if not _test_db:
    _fd, _test_db = tempfile.mkstemp(suffix=".db", prefix="test_migrations_")
    os.close(_fd)
    os.environ["APP_DB_PATH"] = _test_db
if not os.environ.get("SESSION_SECRET"):
    os.environ["SESSION_SECRET"] = "test-secret-migrations"

from config import DB_PATH  # noqa: E402
from database import db  # noqa: E402
from migrations_runner import apply_migrations  # noqa: E402


def test_apply_migrations_is_idempotent_and_records_versions():
    apply_migrations(DB_PATH)
    apply_migrations(DB_PATH)  # idempotente

    conn = db()
    try:
        row = conn.execute("SELECT COUNT(*) AS n FROM schema_migrations").fetchone()
        n = int(row["n"] if isinstance(row, dict) else row[0])
        assert n > 0
        last = conn.execute("SELECT version FROM schema_migrations ORDER BY version DESC LIMIT 1").fetchone()
        assert last is not None
        v = (last["version"] if isinstance(last, dict) else last[0]) or ""
        assert str(v).strip() != ""
    finally:
        conn.close()

