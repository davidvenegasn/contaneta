"""Tests for per-invoice CFDI deductibility auto-detection and persistence."""
import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

ISSUER_ID = 77777


@pytest.fixture(scope="module", autouse=True)
def _isolated_db():
    """Use a fresh temp DB with cfdi_deductibility and sat_cfdi tables."""
    fd, db_path = tempfile.mkstemp(suffix=".db", prefix="test_deduct_")
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
                percentage REAL NOT NULL DEFAULT 100 CHECK(percentage >= 0 AND percentage <= 100),
                source TEXT NOT NULL DEFAULT 'default' CHECK(source IN ('auto','manual','default')),
                auto_reason TEXT,
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE(cfdi_uuid, issuer_id)
            );
            CREATE TABLE IF NOT EXISTS sat_cfdi (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                issuer_id INTEGER NOT NULL,
                uuid TEXT NOT NULL,
                direction TEXT,
                status TEXT,
                fecha_emision TEXT,
                rfc_emisor TEXT,
                nombre_emisor TEXT,
                rfc_receptor TEXT,
                nombre_receptor TEXT,
                total REAL,
                moneda TEXT,
                clave_prod_serv TEXT,
                concepto TEXT,
                forma_pago TEXT,
                uso_cfdi TEXT,
                impuestos REAL
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


class TestDetectDeductibility:
    """Pure function tests — no DB needed."""

    def test_should_detect_professional_services(self):
        from services.fiscal.deductibility import detect_deductibility
        pct, source, reason = detect_deductibility({"clave_prod_serv": "84111506"})
        assert pct == 100
        assert source == "auto"
        assert reason == "professional_services"

    def test_should_detect_restaurant_by_concepto(self):
        from services.fiscal.deductibility import detect_deductibility
        pct, source, reason = detect_deductibility({"concepto": "RESTAURANTE EL BUEN SABOR"})
        assert pct == 8.5
        assert source == "auto"
        assert reason == "restaurant"

    def test_should_detect_fuel_cash(self):
        from services.fiscal.deductibility import detect_deductibility
        pct, source, reason = detect_deductibility({
            "clave_prod_serv": "15101505",
            "forma_pago": "01",
        })
        assert pct == 0
        assert source == "auto"
        assert reason == "fuel_cash"

    def test_should_default_100_for_unknown(self):
        from services.fiscal.deductibility import detect_deductibility
        pct, source, reason = detect_deductibility({"clave_prod_serv": "99999999"})
        assert pct == 100.0
        assert source == "default"
        assert reason == ""


class TestSetAndGet:
    """Persistence tests with DB."""

    def test_should_set_then_get_manual(self):
        from services.fiscal.deductibility import set_deductibility, get_deductibility
        set_deductibility(ISSUER_ID, "UUID-MANUAL-001", 50.0, "manual", "user choice")
        result = get_deductibility(ISSUER_ID, "UUID-MANUAL-001")
        assert result["percentage"] == 50.0
        assert result["source"] == "manual"

    def test_should_invalid_percentage_raises(self):
        from services.fiscal.deductibility import set_deductibility
        with pytest.raises(ValueError, match="percentage must be 0-100"):
            set_deductibility(ISSUER_ID, "UUID-BAD", -10.0)

    def test_should_invalid_percentage_over_100_raises(self):
        from services.fiscal.deductibility import set_deductibility
        with pytest.raises(ValueError, match="percentage must be 0-100"):
            set_deductibility(ISSUER_ID, "UUID-BAD", 110.0)

    def test_should_upsert_overwrites(self):
        from services.fiscal.deductibility import set_deductibility, get_deductibility
        set_deductibility(ISSUER_ID, "UUID-UPSERT", 100.0, "auto", "office_supplies")
        set_deductibility(ISSUER_ID, "UUID-UPSERT", 25.0, "manual", "user override")
        result = get_deductibility(ISSUER_ID, "UUID-UPSERT")
        assert result["percentage"] == 25.0
        assert result["source"] == "manual"

    def test_should_return_default_for_missing_cfdi(self):
        from services.fiscal.deductibility import get_deductibility
        result = get_deductibility(ISSUER_ID, "UUID-NONEXISTENT")
        assert result["percentage"] == 100.0
        assert result["source"] == "default"


class TestGetDeductibilityMap:
    """Bulk fetch tests."""

    def test_should_return_map_for_known_uuids(self):
        from services.fiscal.deductibility import set_deductibility, get_deductibility_map
        set_deductibility(ISSUER_ID, "UUID-MAP-1", 100.0, "auto", "pro")
        set_deductibility(ISSUER_ID, "UUID-MAP-2", 8.5, "auto", "restaurant")
        result = get_deductibility_map(ISSUER_ID, ["UUID-MAP-1", "UUID-MAP-2", "UUID-MAP-MISSING"])
        assert "UUID-MAP-1" in result
        assert "UUID-MAP-2" in result
        assert result["UUID-MAP-2"]["percentage"] == 8.5
        assert "UUID-MAP-MISSING" not in result

    def test_should_return_empty_for_empty_list(self):
        from services.fiscal.deductibility import get_deductibility_map
        assert get_deductibility_map(ISSUER_ID, []) == {}
