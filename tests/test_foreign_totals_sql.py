"""Tests for compute_totals SQL aggregate — verifies totals match across methods."""
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
    fd, db_path = tempfile.mkstemp(suffix=".db", prefix="test_fi_totals_sql_")
    os.close(fd)

    import database
    old_path = database.DB_PATH
    database.DB_PATH = db_path

    from services.invoices import foreign_invoices as fi
    fi.ensure_table()

    yield fi

    database.DB_PATH = old_path
    try:
        os.unlink(db_path)
    except OSError:
        pass


class TestComputeTotalsBasic:
    """compute_totals should correctly aggregate gastos and ingresos."""

    def test_should_separate_gastos_and_ingresos(self, _isolated_db):
        fi = _isolated_db
        fi.create(ISSUER_ID, "GASTO", "2026-07-01", "CT-001", "Vendor A",
                  "Service A", "USD", 100.0, 20.0)
        fi.create(ISSUER_ID, "GASTO", "2026-07-02", "CT-002", "Vendor B",
                  "Service B", "USD", 50.0, 20.0)
        fi.create(ISSUER_ID, "INGRESO", "2026-07-03", "CT-003", "Client C",
                  "Project C", "USD", 200.0, 20.0)

        totals = fi.compute_totals(ISSUER_ID, period_month="2026-07")
        assert abs(totals["sum_gastos"] - 3000.0) <= 0.01  # (100+50)*20
        assert abs(totals["sum_ingresos"] - 4000.0) <= 0.01  # 200*20

    def test_should_match_list_based_sum(self, _isolated_db):
        """compute_totals must equal summing list_invoices items."""
        fi = _isolated_db
        items = fi.list_invoices(ISSUER_ID, period_month="2026-07")
        list_gastos = sum(r["monto_mxn"] for r in items if r["tipo"] == "GASTO")
        list_ingresos = sum(r["monto_mxn"] for r in items if r["tipo"] == "INGRESO")

        totals = fi.compute_totals(ISSUER_ID, period_month="2026-07")
        assert abs(totals["sum_gastos"] - list_gastos) <= 0.01
        assert abs(totals["sum_ingresos"] - list_ingresos) <= 0.01

    def test_should_return_zeros_for_empty_period(self, _isolated_db):
        fi = _isolated_db
        totals = fi.compute_totals(ISSUER_ID, period_month="2099-01")
        assert totals["sum_ingresos"] == 0.0
        assert totals["sum_gastos"] == 0.0

    def test_should_return_floats(self, _isolated_db):
        fi = _isolated_db
        totals = fi.compute_totals(ISSUER_ID, period_month="2099-01")
        assert isinstance(totals["sum_ingresos"], float)
        assert isinstance(totals["sum_gastos"], float)


class TestComputeTotalsAnnual:
    """compute_totals should work with annual period (YYYY)."""

    def test_should_aggregate_across_months_for_annual(self, _isolated_db):
        fi = _isolated_db
        fi.create(ISSUER_ID, "GASTO", "2025-01-15", "CT-008", "Vendor H",
                  "Item H", "USD", 10.0, 20.0)
        fi.create(ISSUER_ID, "GASTO", "2025-06-15", "CT-009", "Vendor I",
                  "Item I", "USD", 20.0, 20.0)
        fi.create(ISSUER_ID, "INGRESO", "2025-12-01", "CT-010", "Client J",
                  "Project J", "USD", 50.0, 20.0)

        totals = fi.compute_totals(ISSUER_ID, period_month="2025")
        assert abs(totals["sum_gastos"] - 600.0) <= 0.01   # (10+20)*20
        assert abs(totals["sum_ingresos"] - 1000.0) <= 0.01  # 50*20

    def test_should_not_mix_years(self, _isolated_db):
        fi = _isolated_db
        # 2025 data was inserted above; 2026-07 data also exists
        totals_2025 = fi.compute_totals(ISSUER_ID, period_month="2025")
        totals_2026 = fi.compute_totals(ISSUER_ID, period_month="2026")
        # They should not overlap
        assert totals_2025["sum_gastos"] != totals_2026["sum_gastos"]
