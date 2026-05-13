"""Health check service functions for system diagnostics.

Provides granular health checks (database, disk, migrations, system info)
that can be composed by the router layer or called independently.
This module does NOT replace the existing /health endpoint in app.py.
"""

import logging
import os
import platform
import shutil
import sys
import time

logger = logging.getLogger(__name__)

# Module-level start time for uptime calculation
_start_time = time.monotonic()


def check_database() -> dict:
    """Verify database connectivity, version, and WAL mode status.

    Returns:
        Dict with keys: ok, sqlite_version, journal_mode, foreign_keys, error.
    """
    from config import DB_PATH

    result = {
        "ok": False,
        "sqlite_version": None,
        "journal_mode": None,
        "foreign_keys": None,
        "db_path_exists": False,
        "error": None,
    }

    try:
        result["db_path_exists"] = os.path.isfile(DB_PATH)
        if not result["db_path_exists"]:
            result["error"] = "database file not found"
            return result

        from database import db

        conn = db()
        try:
            # SQLite version
            row = conn.execute("SELECT sqlite_version()").fetchone()
            if isinstance(row, dict):
                result["sqlite_version"] = list(row.values())[0]
            else:
                result["sqlite_version"] = row[0]

            # Journal mode (should be WAL)
            row = conn.execute("PRAGMA journal_mode").fetchone()
            if isinstance(row, dict):
                result["journal_mode"] = list(row.values())[0]
            else:
                result["journal_mode"] = row[0]

            # Foreign keys status
            row = conn.execute("PRAGMA foreign_keys").fetchone()
            if isinstance(row, dict):
                fk_val = list(row.values())[0]
            else:
                fk_val = row[0]
            result["foreign_keys"] = bool(fk_val)

            result["ok"] = True
        finally:
            conn.close()
    except Exception as exc:
        result["error"] = str(exc)
        logger.warning("Database health check failed: %s", exc)

    return result


def check_disk_space() -> dict:
    """Check available disk space on the partition hosting the app.

    Returns:
        Dict with keys: ok, total_mb, used_mb, free_mb, usage_percent, error.
    """
    from config import BASE_DIR

    result = {
        "ok": False,
        "total_mb": None,
        "used_mb": None,
        "free_mb": None,
        "usage_percent": None,
        "error": None,
    }

    try:
        usage = shutil.disk_usage(BASE_DIR)
        result["total_mb"] = usage.total // (1024 * 1024)
        result["used_mb"] = usage.used // (1024 * 1024)
        result["free_mb"] = usage.free // (1024 * 1024)
        if usage.total > 0:
            result["usage_percent"] = round((usage.used / usage.total) * 100, 1)
        else:
            result["usage_percent"] = 0.0
        # Consider healthy if more than 500 MB free
        result["ok"] = result["free_mb"] > 500
    except Exception as exc:
        result["error"] = str(exc)
        logger.warning("Disk space check failed: %s", exc)

    return result


def check_migrations() -> dict:
    """Verify all migration files have been applied to the database.

    Returns:
        Dict with keys: ok, applied_count, latest_version, pending, error.
    """
    result = {
        "ok": False,
        "applied_count": 0,
        "latest_version": None,
        "pending": [],
        "error": None,
    }

    try:
        from database import db_rows
        from migrations_runner import DEFAULT_MIGRATIONS_DIR, _list_migration_files

        # Get applied versions from DB
        try:
            rows = db_rows("SELECT version FROM schema_migrations ORDER BY version")
            applied_versions = {r["version"] for r in rows}
        except Exception:
            # Table may not exist yet
            applied_versions = set()

        result["applied_count"] = len(applied_versions)
        if applied_versions:
            result["latest_version"] = sorted(applied_versions)[-1]

        # Compare against migration files on disk
        migration_files = _list_migration_files(DEFAULT_MIGRATIONS_DIR)
        all_versions = {version for version, _ in migration_files}
        pending = sorted(all_versions - applied_versions)
        result["pending"] = pending
        result["ok"] = len(pending) == 0
    except Exception as exc:
        result["error"] = str(exc)
        logger.warning("Migrations health check failed: %s", exc)

    return result


def get_system_info() -> dict:
    """Gather basic system information for diagnostics.

    Returns:
        Dict with keys: python_version, platform, architecture,
        pid, uptime_seconds, cwd.
    """
    return {
        "python_version": sys.version,
        "platform": platform.platform(),
        "architecture": platform.machine(),
        "pid": os.getpid(),
        "uptime_seconds": round(time.monotonic() - _start_time, 1),
        "cwd": os.getcwd(),
    }
