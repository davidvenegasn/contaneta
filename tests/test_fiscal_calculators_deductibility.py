"""Tests for deductibility-adjusted fiscal totals."""
import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

ISSUER_ID = 66666


@pytest.fixture(scope="module", autouse=True)
def _isolated_db():
    """Fresh temp DB with sat_cfdi and cfdi_deductibility."""
    fd, db_path = tempfile.mkstemp(suffix=".db", prefix="test_fiscal_calc_")
    os.close(fd)

    import database
    old_path = database.DB_PATH
    database.DB_PATH = db_path

    conn = database.db()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS cfdi_deductibility (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cfdi_uuid TEXT NOT NULL,
                issuer_id INTEGER NOT NULL,
                percentage REAL NOT NULL DEFAULT 100,
                source TEXT NOT NULL DEFAULT 'default',
                auto_reason TEXT,
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE(cfdi_uuid, issuer_id)
            );
            CREATE TABLE IF NOT EXISTS sat_cfdi (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                issuer_id INTEGER NOT NULL,
                uuid TEXT NOT NULL,
                direction TEXT NOT NULL,
                status TEXT,
                fecha_emision TEXT,
                rfc_emisor TEXT,
                nombre_emisor TEXT,
                rfc_receptor TEXT,
                nombre_receptor TEXT,
                total REAL,
                subtotal REAL,
                impuestos REAL,
                moneda TEXT,
                tipo_comprobante TEXT,
                concepto TEXT,
                forma_pago TEXT
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


def _insert_cfdi(uuid, subtotal, impuestos, fecha="2026-03-15"):
    from database import db
    conn = db()
    try:
        conn.execute(
            """INSERT INTO sat_cfdi (issuer_id, uuid, direction, status, fecha_emision,
                   rfc_emisor, nombre_emisor, rfc_receptor, nombre_receptor,
                   total, subtotal, impuestos, moneda)
               VALUES (?, ?, 'received', 'vigente', ?, 'XAXX010101000', 'Proveedor',
                       'RFC66666', 'Issuer', ?, ?, ?, 'MXN')""",
            (ISSUER_ID, uuid, fecha, subtotal + impuestos, subtotal, impuestos),
        )
        conn.commit()
    finally:
        conn.close()


class TestComputeDeductibleTotals:

    def test_should_compute_proportional_totals_with_mixed_percentages(self):
        from services.fiscal.deductibility import compute_deductible_totals, set_deductibility

        _insert_cfdi("UUID-FULL", 10000.0, 1600.0)
        _insert_cfdi("UUID-HALF", 5000.0, 800.0)
        _insert_cfdi("UUID-REST", 2000.0, 320.0)

        set_deductibility(ISSUER_ID, "UUID-FULL", 100.0, "auto", "pro")
        set_deductibility(ISSUER_ID, "UUID-HALF", 50.0, "manual", "")
        set_deductibility(ISSUER_ID, "UUID-REST", 8.5, "auto", "restaurant")

        result = compute_deductible_totals(ISSUER_ID, "2026-03")

        # Gastos deducibles: 10000*1.0 + 5000*0.5 + 2000*0.085 = 10000 + 2500 + 170 = 12670
        assert abs(result["gastos_deducibles"] - 12670.0) <= 0.01
        # IVA acreditable: 1600*1.0 + 800*0.5 + 320*0.085 = 1600 + 400 + 27.2 = 2027.2
        assert abs(result["iva_acreditable"] - 2027.2) <= 0.01
        # Brutos
        assert abs(result["gastos_brutos"] - 17000.0) <= 0.01
        assert abs(result["iva_bruto"] - 2720.0) <= 0.01

    def test_should_default_100_for_cfdi_without_record(self):
        from services.fiscal.deductibility import compute_deductible_totals

        _insert_cfdi("UUID-NORECORD", 3000.0, 480.0, "2026-04-10")

        result = compute_deductible_totals(ISSUER_ID, "2026-04")
        # Default 100%: full deduction
        assert abs(result["gastos_deducibles"] - 3000.0) <= 0.01
        assert abs(result["iva_acreditable"] - 480.0) <= 0.01

    def test_should_return_detail_per_invoice(self):
        from services.fiscal.deductibility import compute_deductible_totals

        result = compute_deductible_totals(ISSUER_ID, "2026-03")
        assert len(result["detail"]) == 3
        for d in result["detail"]:
            assert "uuid" in d
            assert "deductibility_pct" in d
            assert "deducible" in d

    def test_should_return_zeros_for_empty_month(self):
        from services.fiscal.deductibility import compute_deductible_totals

        result = compute_deductible_totals(ISSUER_ID, "2099-01")
        assert result["gastos_deducibles"] == 0.0
        assert result["iva_acreditable"] == 0.0
        assert result["detail"] == []
