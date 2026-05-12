"""Tests for backfill script dry-run: verifies it does NOT modify the DB."""
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

ISSUER_ID = 55555


@pytest.fixture(scope="module", autouse=True)
def _isolated_db():
    """Use a fresh temp DB for this module."""
    fd, db_path = tempfile.mkstemp(suffix=".db", prefix="test_backfill_")
    os.close(fd)

    import database
    old_path = database.DB_PATH
    database.DB_PATH = db_path

    from services.invoices import foreign_invoices as fi
    fi.ensure_table()

    # Create dof_rates table
    conn = database.db()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS dof_rates (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              date TEXT NOT NULL,
              currency TEXT NOT NULL,
              rate_to_mxn REAL NOT NULL,
              source TEXT NOT NULL DEFAULT 'banxico_dof',
              series TEXT,
              fetched_at TEXT NOT NULL DEFAULT (datetime('now')),
              UNIQUE(date, currency)
            );
        """)
    finally:
        conn.close()

    # Create test invoices with known rates
    fi.create(ISSUER_ID, "GASTO", "2026-05-01", "BF-001",
              "Vendor A", "Service A", "USD", 100.0, 20.0)
    fi.create(ISSUER_ID, "INGRESO", "2026-05-02", "BF-002",
              "Client B", "Export B", "EUR", 200.0, 22.0)

    yield

    database.DB_PATH = old_path
    try:
        os.unlink(db_path)
    except OSError:
        pass


class TestBackfillDryRun:
    def test_dry_run_does_not_modify_db(self):
        from database import db_rows
        # Snapshot before
        before = db_rows(
            "SELECT id, tipo_cambio, monto_mxn FROM foreign_invoices "
            "WHERE issuer_id = ? ORDER BY id",
            (ISSUER_ID,),
        )
        assert len(before) == 2

        # Run backfill in dry-run (mock get_rate to return different rates)
        with patch("services.invoices.banxico_client.get_rate") as mock_rate:
            mock_rate.return_value = 99.99  # Very different rate
            sys.path.insert(0, str(ROOT / "scripts"))
            from backfill_foreign_invoices_rates import main
            main(dry_run=True)

        # Snapshot after
        after = db_rows(
            "SELECT id, tipo_cambio, monto_mxn FROM foreign_invoices "
            "WHERE issuer_id = ? ORDER BY id",
            (ISSUER_ID,),
        )
        # Nothing should have changed
        for b, a in zip(before, after):
            assert b["tipo_cambio"] == a["tipo_cambio"]
            assert b["monto_mxn"] == a["monto_mxn"]
