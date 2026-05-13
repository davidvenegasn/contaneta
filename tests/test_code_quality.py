"""Tests for code quality configuration and health check services."""

import os
import sqlite3
import sys
import tempfile
from pathlib import Path

# Ensure project root is on sys.path and test DB is configured
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_test_db = os.environ.get("APP_DB_PATH")
if not _test_db:
    _fd, _test_db = tempfile.mkstemp(suffix=".db", prefix="test_cq_")
    os.close(_fd)
    os.environ["APP_DB_PATH"] = _test_db
if not os.environ.get("SESSION_SECRET"):
    os.environ["SESSION_SECRET"] = "test-secret-code-quality"


def _ensure_test_db():
    """Bootstrap a minimal test DB with schema_migrations table and a few versions.

    This avoids calling apply_migrations() which may fail on pre-existing
    broken migration SQL files unrelated to this test module.
    """
    from config import DB_PATH

    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            applied_at TEXT
        )
    """)
    # Insert a couple of fake applied versions if table is empty
    cur = conn.execute("SELECT COUNT(*) FROM schema_migrations")
    if cur.fetchone()[0] == 0:
        conn.execute(
            "INSERT INTO schema_migrations (version, applied_at) VALUES ('001', datetime('now'))"
        )
        conn.execute(
            "INSERT INTO schema_migrations (version, applied_at) VALUES ('002', datetime('now'))"
        )
    conn.commit()
    conn.close()


# Bootstrap DB once at import time
_ensure_test_db()


# --- Deliverable 1: ruff.toml ---


def test_ruff_toml_exists():
    """ruff.toml must be present at project root."""
    ruff_path = ROOT / "ruff.toml"
    assert ruff_path.is_file(), f"ruff.toml not found at {ruff_path}"


def test_ruff_toml_is_valid_toml():
    """ruff.toml must parse as valid TOML."""
    import tomllib

    ruff_path = ROOT / "ruff.toml"
    with open(ruff_path, "rb") as f:
        data = tomllib.load(f)
    assert isinstance(data, dict)


def test_ruff_toml_target_version():
    """ruff.toml must target Python 3.11+."""
    import tomllib

    ruff_path = ROOT / "ruff.toml"
    with open(ruff_path, "rb") as f:
        data = tomllib.load(f)
    assert "target-version" in data
    assert data["target-version"] >= "py311"


def test_ruff_toml_line_length():
    """ruff.toml must set line-length to 120."""
    import tomllib

    ruff_path = ROOT / "ruff.toml"
    with open(ruff_path, "rb") as f:
        data = tomllib.load(f)
    assert data.get("line-length") == 120


def test_ruff_toml_selected_rules():
    """ruff.toml must enable E, F, I, B, UP rules."""
    import tomllib

    ruff_path = ROOT / "ruff.toml"
    with open(ruff_path, "rb") as f:
        data = tomllib.load(f)
    selected = data.get("lint", {}).get("select", [])
    for rule in ["E", "F", "I", "B", "UP"]:
        assert rule in selected, f"Rule {rule} not in ruff select list"


def test_ruff_toml_ignored_rules():
    """ruff.toml must ignore E501, B008, B904."""
    import tomllib

    ruff_path = ROOT / "ruff.toml"
    with open(ruff_path, "rb") as f:
        data = tomllib.load(f)
    ignored = data.get("lint", {}).get("ignore", [])
    for rule in ["E501", "B008", "B904"]:
        assert rule in ignored, f"Rule {rule} not in ruff ignore list"


def test_ruff_toml_excludes_directories():
    """ruff.toml must exclude .venv, __pycache__, migrations, sat_sync."""
    import tomllib

    ruff_path = ROOT / "ruff.toml"
    with open(ruff_path, "rb") as f:
        data = tomllib.load(f)
    excluded = data.get("exclude", [])
    for dirname in [".venv", "__pycache__", "migrations", "sat_sync"]:
        assert dirname in excluded, f"Directory {dirname} not in ruff exclude list"


# --- Deliverable 2: pyproject.toml ---


def test_pyproject_toml_exists():
    """pyproject.toml must be present at project root."""
    path = ROOT / "pyproject.toml"
    assert path.is_file(), f"pyproject.toml not found at {path}"


def test_pyproject_toml_pytest_section():
    """pyproject.toml must contain pytest configuration."""
    import tomllib

    path = ROOT / "pyproject.toml"
    with open(path, "rb") as f:
        data = tomllib.load(f)
    pytest_opts = data.get("tool", {}).get("pytest", {}).get("ini_options", {})
    assert "testpaths" in pytest_opts
    assert "tests" in pytest_opts["testpaths"]


# --- Deliverable 3: health check functions ---


def test_check_database_returns_expected_keys():
    """check_database() must return dict with documented keys."""
    from services.health import check_database

    result = check_database()
    assert isinstance(result, dict)
    for key in ("ok", "sqlite_version", "journal_mode", "foreign_keys", "db_path_exists", "error"):
        assert key in result, f"Missing key: {key}"


def test_check_database_connects_successfully():
    """check_database() must report ok=True with a valid database."""
    from services.health import check_database

    result = check_database()
    assert result["ok"] is True
    assert result["sqlite_version"] is not None
    assert result["db_path_exists"] is True
    assert result["error"] is None


def test_check_database_reports_wal_mode():
    """check_database() must confirm WAL journal mode."""
    from services.health import check_database

    result = check_database()
    assert result["journal_mode"] == "wal"


def test_check_disk_space_returns_expected_keys():
    """check_disk_space() must return dict with documented keys."""
    from services.health import check_disk_space

    result = check_disk_space()
    assert isinstance(result, dict)
    for key in ("ok", "total_mb", "used_mb", "free_mb", "usage_percent", "error"):
        assert key in result, f"Missing key: {key}"


def test_check_disk_space_reports_valid_values():
    """check_disk_space() must return positive numeric values."""
    from services.health import check_disk_space

    result = check_disk_space()
    assert result["ok"] is True  # dev machine should have > 500 MB free
    assert result["total_mb"] > 0
    assert result["free_mb"] > 0
    assert 0 <= result["usage_percent"] <= 100
    assert result["error"] is None


def test_check_migrations_returns_expected_keys():
    """check_migrations() must return dict with documented keys."""
    from services.health import check_migrations

    result = check_migrations()
    assert isinstance(result, dict)
    for key in ("ok", "applied_count", "latest_version", "pending", "error"):
        assert key in result, f"Missing key: {key}"


def test_check_migrations_reports_applied_count():
    """check_migrations() must report applied migrations from schema_migrations table."""
    from services.health import check_migrations

    result = check_migrations()
    # We seeded at least 2 versions in _ensure_test_db
    assert result["applied_count"] >= 2
    assert result["latest_version"] is not None
    assert result["error"] is None


def test_get_system_info_returns_expected_keys():
    """get_system_info() must return dict with documented keys."""
    from services.health import get_system_info

    result = get_system_info()
    assert isinstance(result, dict)
    for key in ("python_version", "platform", "architecture", "pid", "uptime_seconds", "cwd"):
        assert key in result, f"Missing key: {key}"


def test_get_system_info_returns_valid_data():
    """get_system_info() must return sensible values."""
    from services.health import get_system_info

    result = get_system_info()
    assert "3." in result["python_version"]  # Python 3.x
    assert result["pid"] > 0
    assert result["uptime_seconds"] >= 0
    assert len(result["platform"]) > 0
    assert len(result["architecture"]) > 0
    assert len(result["cwd"]) > 0
