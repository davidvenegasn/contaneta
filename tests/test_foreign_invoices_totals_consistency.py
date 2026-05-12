"""Tests for foreign invoice data consistency: tipo normalization, monto_mxn validity."""
import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

ISSUER_ID = 88888


@pytest.fixture(scope="module", autouse=True)
def _isolated_db():
    """Use a fresh temp DB for this module."""
    fd, db_path = tempfile.mkstemp(suffix=".db", prefix="test_fi_consist_")
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


class TestTipoNormalization:
    def test_tipo_stored_upper(self, _isolated_db):
        fi = _isolated_db
        inv = fi.create(ISSUER_ID, "ingreso", "2026-03-01", "NORM-001",
                        "Test Co", "Service", "USD", 100.0, 20.0)
        assert inv["tipo"] == "INGRESO"

    def test_tipo_stored_upper_with_whitespace(self, _isolated_db):
        fi = _isolated_db
        inv = fi.create(ISSUER_ID, "  gasto  ", "2026-03-02", "NORM-002",
                        "Test Co 2", "Product", "EUR", 50.0, 22.0)
        assert inv["tipo"] == "GASTO"

    def test_invalid_tipo_raises(self, _isolated_db):
        fi = _isolated_db
        with pytest.raises(ValueError, match="INGRESO or GASTO"):
            fi.create(ISSUER_ID, "INVALID", "2026-03-03", "NORM-003",
                      "Test Co 3", "Other", "USD", 10.0, 20.0)


class TestMontoMxnConsistency:
    def test_monto_mxn_not_null(self, _isolated_db):
        fi = _isolated_db
        inv = fi.create(ISSUER_ID, "INGRESO", "2026-04-01", "MXN-001",
                        "Alpha Inc", "Consulting", "USD", 250.0, 19.5)
        assert inv["monto_mxn"] is not None
        assert inv["monto_mxn"] > 0

    def test_monto_mxn_matches_calculation(self, _isolated_db):
        fi = _isolated_db
        inv = fi.create(ISSUER_ID, "GASTO", "2026-04-02", "MXN-002",
                        "Beta LLC", "License", "EUR", 100.0, 22.35)
        expected = round(100.0 * 22.35, 2)
        assert abs(inv["monto_mxn"] - expected) <= 0.01

    def test_monto_mxn_precision_small_amount(self, _isolated_db):
        fi = _isolated_db
        inv = fi.create(ISSUER_ID, "GASTO", "2026-04-03", "MXN-003",
                        "Gamma SA", "Subscription", "USD", 0.99, 20.45)
        expected = round(0.99 * 20.45, 2)
        assert abs(inv["monto_mxn"] - expected) <= 0.01

    def test_monto_mxn_precision_large_amount(self, _isolated_db):
        fi = _isolated_db
        inv = fi.create(ISSUER_ID, "INGRESO", "2026-04-04", "MXN-004",
                        "Delta Corp", "Project", "USD", 99999.99, 20.45)
        expected = round(99999.99 * 20.45, 2)
        assert abs(inv["monto_mxn"] - expected) <= 0.01


class TestListTotalsMatch:
    def test_sum_matches_individual_monto_mxn(self, _isolated_db):
        fi = _isolated_db
        # Create known invoices in a unique month
        fi.create(ISSUER_ID, "GASTO", "2026-06-01", "SUM-001",
                  "Vendor A", "Item A", "USD", 50.0, 20.0)
        fi.create(ISSUER_ID, "GASTO", "2026-06-15", "SUM-002",
                  "Vendor B", "Item B", "EUR", 30.0, 22.0)
        fi.create(ISSUER_ID, "INGRESO", "2026-06-20", "SUM-003",
                  "Client C", "Service C", "USD", 200.0, 20.0)

        items = fi.list_invoices(ISSUER_ID, period_month="2026-06")
        assert len(items) == 3

        sum_gastos = sum(r["monto_mxn"] for r in items if r["tipo"] == "GASTO")
        sum_ingresos = sum(r["monto_mxn"] for r in items if r["tipo"] == "INGRESO")

        assert abs(sum_gastos - (50.0 * 20.0 + 30.0 * 22.0)) <= 0.01
        assert abs(sum_ingresos - (200.0 * 20.0)) <= 0.01
