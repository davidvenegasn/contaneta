"""Tests for Job 23 — Performance Optimizations (cache, static versioning, indexes)."""

import os
import sys
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Ensure test DB is configured before importing database modules
_test_db = os.environ.get("APP_DB_PATH")
if not _test_db:
    _fd, _test_db = tempfile.mkstemp(suffix=".db", prefix="test_perf_")
    os.close(_fd)
    os.environ["APP_DB_PATH"] = _test_db
if not os.environ.get("SESSION_SECRET"):
    os.environ["SESSION_SECRET"] = "test-secret-perf"


# ---------------------------------------------------------------------------
# Cache tests
# ---------------------------------------------------------------------------
from services import cache as cache_service


class TestCacheSetGet:
    """Test basic cache set and get operations."""

    def setup_method(self):
        cache_service.clear()

    def test_should_return_none_for_missing_key(self):
        assert cache_service.get("nonexistent") is None

    def test_should_store_and_retrieve_value(self):
        cache_service.set("greeting", "hello")
        assert cache_service.get("greeting") == "hello"

    def test_should_store_different_value_types(self):
        cache_service.set("int_val", 42)
        cache_service.set("list_val", [1, 2, 3])
        cache_service.set("dict_val", {"a": 1})
        assert cache_service.get("int_val") == 42
        assert cache_service.get("list_val") == [1, 2, 3]
        assert cache_service.get("dict_val") == {"a": 1}

    def test_should_overwrite_existing_key(self):
        cache_service.set("key", "old")
        cache_service.set("key", "new")
        assert cache_service.get("key") == "new"


class TestCacheDelete:
    """Test cache delete operation."""

    def setup_method(self):
        cache_service.clear()

    def test_should_remove_existing_key(self):
        cache_service.set("to_remove", "val")
        cache_service.delete("to_remove")
        assert cache_service.get("to_remove") is None

    def test_should_not_raise_when_deleting_missing_key(self):
        cache_service.delete("missing_key")  # no error


class TestCacheClear:
    """Test cache clear operation."""

    def setup_method(self):
        cache_service.clear()

    def test_should_remove_all_entries(self):
        cache_service.set("a", 1)
        cache_service.set("b", 2)
        cache_service.set("c", 3)
        cache_service.clear()
        assert cache_service.get("a") is None
        assert cache_service.get("b") is None
        assert cache_service.get("c") is None


class TestCacheTTL:
    """Test cache TTL expiration."""

    def setup_method(self):
        cache_service.clear()

    def test_should_expire_after_ttl(self):
        cache_service.set("short_lived", "value", ttl=1)
        assert cache_service.get("short_lived") == "value"
        time.sleep(1.1)
        assert cache_service.get("short_lived") is None

    def test_should_not_expire_before_ttl(self):
        cache_service.set("longer_lived", "value", ttl=10)
        assert cache_service.get("longer_lived") == "value"

    def test_should_evict_expired_entries(self):
        cache_service.set("expires", "val", ttl=1)
        cache_service.set("stays", "val", ttl=60)
        time.sleep(1.1)
        evicted = cache_service.evict_expired()
        assert evicted == 1
        assert cache_service.get("expires") is None
        assert cache_service.get("stays") == "val"


class TestCacheThreadSafety:
    """Test cache thread safety under concurrent access."""

    def setup_method(self):
        cache_service.clear()

    def test_should_handle_concurrent_writes(self):
        errors = []
        num_threads = 10
        writes_per_thread = 50

        def writer(thread_id):
            try:
                for i in range(writes_per_thread):
                    cache_service.set(f"t{thread_id}_k{i}", f"v{i}")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(t,)) for t in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Thread errors: {errors}"

        # Verify all writes succeeded
        for t in range(num_threads):
            for i in range(writes_per_thread):
                val = cache_service.get(f"t{t}_k{i}")
                assert val == f"v{i}", f"Missing t{t}_k{i}"

    def test_should_handle_concurrent_reads_and_writes(self):
        errors = []
        cache_service.set("shared", "initial")

        def reader():
            try:
                for _ in range(100):
                    val = cache_service.get("shared")
                    # Value must be either initial, updated, or None (if deleted)
                    assert val in ("initial", "updated", None)
            except Exception as e:
                errors.append(e)

        def writer():
            try:
                for _ in range(100):
                    cache_service.set("shared", "updated")
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=reader),
            threading.Thread(target=reader),
            threading.Thread(target=writer),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Thread errors: {errors}"


# ---------------------------------------------------------------------------
# Static URL versioning tests
# ---------------------------------------------------------------------------
from services import static_version


class TestStaticUrl:
    """Test static_url versioning function."""

    def setup_method(self):
        static_version.clear_cache()

    def test_should_append_version_hash_to_existing_file(self):
        # Use a known static file
        css_dir = os.path.join(ROOT, "static", "css")
        css_files = [f for f in os.listdir(css_dir) if f.endswith(".css")] if os.path.isdir(css_dir) else []
        if not css_files:
            pytest.skip("No CSS files in static/css/ to test with")
        test_file = css_files[0]
        url = static_version.static_url(f"css/{test_file}")
        assert url.startswith(f"/static/css/{test_file}?v=")
        # Hash should be 8 hex chars
        version = url.split("?v=")[1]
        assert len(version) == 8
        assert all(c in "0123456789abcdef" for c in version)

    def test_should_return_plain_url_for_missing_file(self):
        url = static_version.static_url("css/nonexistent_file_xyz.css")
        assert url == "/static/css/nonexistent_file_xyz.css"
        assert "?v=" not in url

    def test_should_cache_hash_across_calls(self):
        css_dir = os.path.join(ROOT, "static", "css")
        css_files = [f for f in os.listdir(css_dir) if f.endswith(".css")] if os.path.isdir(css_dir) else []
        if not css_files:
            pytest.skip("No CSS files in static/css/ to test with")
        test_file = css_files[0]
        url1 = static_version.static_url(f"css/{test_file}")
        url2 = static_version.static_url(f"css/{test_file}")
        assert url1 == url2

    def test_should_strip_leading_slash(self):
        url = static_version.static_url("/css/nonexistent.css")
        assert url == "/static/css/nonexistent.css"

    def test_should_strip_static_prefix(self):
        url = static_version.static_url("static/css/nonexistent.css")
        assert url == "/static/css/nonexistent.css"

    def test_should_produce_different_hashes_for_different_files(self):
        css_dir = os.path.join(ROOT, "static", "css")
        css_files = [f for f in os.listdir(css_dir) if f.endswith(".css")] if os.path.isdir(css_dir) else []
        if len(css_files) < 2:
            pytest.skip("Need at least 2 CSS files to compare hashes")
        url1 = static_version.static_url(f"css/{css_files[0]}")
        url2 = static_version.static_url(f"css/{css_files[1]}")
        # Different files should (very likely) produce different hashes
        hash1 = url1.split("?v=")[1] if "?v=" in url1 else None
        hash2 = url2.split("?v=")[1] if "?v=" in url2 else None
        if hash1 and hash2:
            # Only assert if both files exist and produced hashes
            # They could theoretically collide but very unlikely with real files
            assert hash1 != hash2 or css_files[0] == css_files[1]


# ---------------------------------------------------------------------------
# Migration index tests
# ---------------------------------------------------------------------------
import sqlite3 as _sqlite3


# Minimal table DDL needed to test the 051 migration indexes.
# Only includes columns referenced by indexes.
_SETUP_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS issuers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rfc TEXT
);
CREATE TABLE IF NOT EXISTS invoices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    issuer_id INTEGER NOT NULL,
    status TEXT,
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS customer_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    issuer_id INTEGER NOT NULL,
    rfc TEXT
);
CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    issuer_id INTEGER NOT NULL,
    name TEXT
);
CREATE TABLE IF NOT EXISTS bank_movements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    issuer_id INTEGER NOT NULL,
    fecha TEXT
);
CREATE TABLE IF NOT EXISTS quotations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    issuer_id INTEGER NOT NULL,
    status TEXT
);
CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    issuer_id INTEGER NOT NULL,
    read_at TEXT
);
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    status TEXT
);
"""


def _read_migration_sql() -> str:
    """Read the 051 migration file contents."""
    migration_path = os.path.join(ROOT, "migrations", "051_performance_indexes.sql")
    with open(migration_path, "r", encoding="utf-8") as f:
        return f.read()


class TestPerformanceIndexes:
    """Test that migration 051 creates the expected indexes."""

    @pytest.fixture(autouse=True)
    def _setup_db(self, tmp_path):
        """Create an in-memory DB with minimal tables and apply migration 051."""
        db_path = str(tmp_path / "test_indexes.db")
        self._conn = _sqlite3.connect(db_path)
        self._conn.row_factory = lambda cursor, row: dict(
            zip([c[0] for c in cursor.description], row)
        )
        self._conn.executescript(_SETUP_TABLES_SQL)
        migration_sql = _read_migration_sql()
        self._conn.executescript(migration_sql)
        yield
        self._conn.close()

    def _get_indexes_for_table(self, table: str) -> list[str]:
        """Return list of index names for a table."""
        rows = self._conn.execute(f"PRAGMA index_list({table})").fetchall()
        return [r["name"] for r in rows]

    def test_should_create_invoices_issuer_date_index(self):
        indexes = self._get_indexes_for_table("invoices")
        assert "idx_invoices_issuer_date" in indexes

    def test_should_create_invoices_issuer_status_index(self):
        indexes = self._get_indexes_for_table("invoices")
        assert "idx_invoices_issuer_status" in indexes

    def test_should_create_customer_profiles_issuer_index(self):
        indexes = self._get_indexes_for_table("customer_profiles")
        assert "idx_customer_profiles_issuer" in indexes

    def test_should_create_products_issuer_index(self):
        indexes = self._get_indexes_for_table("products")
        assert "idx_products_issuer" in indexes

    def test_should_create_bank_movements_issuer_date_index(self):
        indexes = self._get_indexes_for_table("bank_movements")
        assert "idx_bank_movements_issuer_date" in indexes

    def test_should_create_quotations_issuer_status_index(self):
        indexes = self._get_indexes_for_table("quotations")
        assert "idx_quotations_issuer_status" in indexes

    def test_should_create_notifications_issuer_read_index(self):
        indexes = self._get_indexes_for_table("notifications")
        assert "idx_notifications_issuer_read" in indexes

    def test_should_create_jobs_status_index(self):
        indexes = self._get_indexes_for_table("jobs")
        assert "idx_jobs_status" in indexes

    def test_should_be_idempotent(self):
        """Running the migration SQL twice should not raise errors."""
        migration_sql = _read_migration_sql()
        # Apply a second time; should not raise
        self._conn.executescript(migration_sql)
        indexes = self._get_indexes_for_table("invoices")
        assert "idx_invoices_issuer_date" in indexes
