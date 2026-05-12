"""Tests for foreign invoices annual view filter."""
import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

ISSUER_ID = 99999


@pytest.fixture(scope="module", autouse=True)
def _isolated_db():
    """Use a fresh temp DB for this module."""
    fd, db_path = tempfile.mkstemp(suffix=".db", prefix="test_fi_annual_")
    os.close(fd)

    import database
    old_path = database.DB_PATH
    database.DB_PATH = db_path

    from services.invoices import foreign_invoices as fi
    fi.ensure_table()
    fi.create(ISSUER_ID, "INGRESO", "2026-01-15", "INV-001", "Acme Corp",
              "Consulting", "USD", 1000.0, 17.5, pais="US")
    fi.create(ISSUER_ID, "GASTO", "2026-02-20", "INV-002", "Beta Inc",
              "Software license", "USD", 500.0, 17.5, pais="US")
    fi.create(ISSUER_ID, "INGRESO", "2026-05-10", "INV-003", "Gamma Ltd",
              "Design work", "EUR", 2000.0, 19.0, pais="DE")

    yield

    database.DB_PATH = old_path
    try:
        os.unlink(db_path)
    except OSError:
        pass


class TestAnnualFilter:
    def test_annual_returns_all(self):
        from services.invoices import foreign_invoices as fi
        items = fi.list_invoices(ISSUER_ID, period_month="2026")
        assert len(items) == 3

    def test_monthly_returns_one(self):
        from services.invoices import foreign_invoices as fi
        items = fi.list_invoices(ISSUER_ID, period_month="2026-02")
        assert len(items) == 1
        assert items[0]["invoice_number"] == "INV-002"

    def test_monthly_returns_none(self):
        from services.invoices import foreign_invoices as fi
        items = fi.list_invoices(ISSUER_ID, period_month="2026-03")
        assert len(items) == 0

    def test_count_annual(self):
        from services.invoices import foreign_invoices as fi
        n = fi.count_invoices(ISSUER_ID, period_month="2026")
        assert n == 3

    def test_count_monthly(self):
        from services.invoices import foreign_invoices as fi
        n = fi.count_invoices(ISSUER_ID, period_month="2026-02")
        assert n == 1

    def test_different_year_empty(self):
        from services.invoices import foreign_invoices as fi
        items = fi.list_invoices(ISSUER_ID, period_month="2025")
        assert len(items) == 0
