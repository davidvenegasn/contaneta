"""Tests for foreign invoice create() with auto-rate from Banxico."""
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

ISSUER_ID = 66666


@pytest.fixture(scope="module", autouse=True)
def _isolated_db():
    """Use a fresh temp DB for this module."""
    fd, db_path = tempfile.mkstemp(suffix=".db", prefix="test_fi_auto_rate_")
    os.close(fd)

    import database
    old_path = database.DB_PATH
    database.DB_PATH = db_path

    from services.invoices import foreign_invoices as fi
    fi.ensure_table()

    # Also create dof_rates table
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

    yield

    database.DB_PATH = old_path
    try:
        os.unlink(db_path)
    except OSError:
        pass


class TestCreateAutoRate:
    @patch("services.invoices.banxico_client.get_rate")
    def test_auto_rate_when_tipo_cambio_zero(self, mock_get_rate):
        mock_get_rate.return_value = 20.45
        from services.invoices import foreign_invoices as fi
        inv = fi.create(ISSUER_ID, "GASTO", "2026-04-15", "AUTO-001",
                        "Vendor X", "Service", "USD", 100.0, 0)
        assert inv["tipo_cambio"] == 20.45
        assert abs(inv["monto_mxn"] - 2045.0) <= 0.01
        mock_get_rate.assert_called_once_with("2026-04-15", "USD")

    @patch("services.invoices.banxico_client.get_rate")
    def test_auto_rate_when_tipo_cambio_negative(self, mock_get_rate):
        mock_get_rate.return_value = 22.0
        from services.invoices import foreign_invoices as fi
        inv = fi.create(ISSUER_ID, "INGRESO", "2026-04-16", "AUTO-002",
                        "Client Y", "Export", "EUR", 50.0, -1)
        assert inv["tipo_cambio"] == 22.0
        assert abs(inv["monto_mxn"] - 1100.0) <= 0.01

    @patch("services.invoices.banxico_client.get_rate")
    def test_keeps_manual_rate_when_provided(self, mock_get_rate):
        from services.invoices import foreign_invoices as fi
        inv = fi.create(ISSUER_ID, "GASTO", "2026-04-17", "AUTO-003",
                        "Vendor Z", "License", "USD", 10.0, 19.5)
        assert inv["tipo_cambio"] == 19.5
        assert abs(inv["monto_mxn"] - 195.0) <= 0.01
        mock_get_rate.assert_not_called()

    @patch("services.invoices.banxico_client.get_rate")
    def test_fallback_when_banxico_unavailable(self, mock_get_rate):
        mock_get_rate.return_value = None
        from services.invoices import foreign_invoices as fi
        # tipo_cambio=0 and Banxico returns None → keeps 0
        inv = fi.create(ISSUER_ID, "GASTO", "2026-04-18", "AUTO-004",
                        "Vendor W", "Hosting", "USD", 20.0, 0)
        assert inv["tipo_cambio"] == 0
        assert inv["monto_mxn"] == 0.0
