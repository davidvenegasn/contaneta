"""Tests for canonical month total calculation — consistency across pages."""
import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_test_db = os.environ.get("APP_DB_PATH")
if not _test_db:
    _fd, _test_db = tempfile.mkstemp(suffix=".db", prefix="test_totals_")
    os.close(_fd)
    os.environ["APP_DB_PATH"] = _test_db
if not os.environ.get("SESSION_SECRET"):
    os.environ["SESSION_SECRET"] = "test-secret-totals"

from config import DB_PATH  # noqa: E402
from database import db  # noqa: E402
from migrations_runner import apply_migrations  # noqa: E402
from services.dashboard import get_monthly_trend  # noqa: E402
from services.sat.sat_sync import get_month_totals  # noqa: E402

ISSUER_ID = 8888
YM = "2026-03"


@pytest.fixture(autouse=True)
def _setup_db():
    """Apply migrations and seed minimal tenant data before each test."""
    apply_migrations(DB_PATH)
    conn = db()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO issuers (id, rfc, razon_social, active, created_at, updated_at) "
            "VALUES (?, 'TOTTEST01', 'Totals Test Co', 1, datetime('now'), datetime('now'))",
            (ISSUER_ID,),
        )
        # Clean sat_cfdi for test issuer
        conn.execute("DELETE FROM sat_cfdi WHERE issuer_id = ?", (ISSUER_ID,))
        conn.commit()
    finally:
        conn.close()
    yield


def _insert_cfdi(*, uuid, direction="issued", total, subtotal=None, impuestos=None,
                 status=None, ym=YM, tipo_comprobante="I"):
    """Insert a sat_cfdi row for testing."""
    conn = db()
    try:
        conn.execute(
            """
            INSERT INTO sat_cfdi
              (issuer_id, uuid, direction, fecha_emision, total, subtotal, impuestos,
               status, tipo_comprobante, rfc_emisor, nombre_emisor)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'XAXX010101000', 'Test Emisor')
            """,
            (ISSUER_ID, uuid, direction, f"{ym}-15T12:00:00",
             total, subtotal, impuestos, status, tipo_comprobante),
        )
        conn.commit()
    finally:
        conn.close()


class TestExcludeCancelledInvoices:
    def test_should_exclude_cancelled_from_month_totals(self):
        _insert_cfdi(uuid="active-001", total=1000, subtotal=862.07, impuestos=137.93)
        _insert_cfdi(uuid="cancel-001", total=500, subtotal=431.03, impuestos=68.97,
                     status="CANCELADO")
        result = get_month_totals(ISSUER_ID, YM, "issued")
        assert abs(result["total_base"] - 862.07) < 0.01

    def test_should_exclude_status_c(self):
        _insert_cfdi(uuid="active-002", total=200, subtotal=172.41)
        _insert_cfdi(uuid="cancel-c", total=100, subtotal=86.21, status="C")
        result = get_month_totals(ISSUER_ID, YM, "issued")
        assert abs(result["total_base"] - 172.41) < 0.01

    def test_should_exclude_status_zero(self):
        _insert_cfdi(uuid="active-003", total=300, subtotal=258.62)
        _insert_cfdi(uuid="cancel-zero", total=150, subtotal=129.31, status="0")
        result = get_month_totals(ISSUER_ID, YM, "issued")
        assert abs(result["total_base"] - 258.62) < 0.01

    def test_should_exclude_cancelada(self):
        _insert_cfdi(uuid="active-004", total=400, subtotal=344.83)
        _insert_cfdi(uuid="cancel-ada", total=200, subtotal=172.41, status="CANCELADA")
        result = get_month_totals(ISSUER_ID, YM, "issued")
        assert abs(result["total_base"] - 344.83) < 0.01

    def test_should_exclude_cancelled_from_trend(self):
        _insert_cfdi(uuid="trend-active", total=1000, subtotal=862.07)
        _insert_cfdi(uuid="trend-cancel", total=500, subtotal=431.03, status="CANCELADO")
        trend = get_monthly_trend(ISSUER_ID, months=3)
        march = [t for t in trend if t["ym"] == YM]
        assert len(march) == 1
        assert abs(march[0]["ingresos"] - 862.07) < 0.01


class TestSubtotalFallback:
    def test_should_use_subtotal_when_available(self):
        _insert_cfdi(uuid="sub-001", total=116, subtotal=100, impuestos=16)
        result = get_month_totals(ISSUER_ID, YM, "issued")
        assert abs(result["total_base"] - 100) < 0.01

    def test_should_fallback_to_total_when_subtotal_null(self):
        _insert_cfdi(uuid="sub-002", total=116, subtotal=None)
        result = get_month_totals(ISSUER_ID, YM, "issued")
        assert abs(result["total_base"] - 116) < 0.01

    def test_should_mix_subtotal_and_fallback(self):
        _insert_cfdi(uuid="sub-003", total=116, subtotal=100)
        _insert_cfdi(uuid="sub-004", total=116, subtotal=None)
        result = get_month_totals(ISSUER_ID, YM, "issued")
        assert abs(result["total_base"] - 216) < 0.01


class TestKpiAndTrendParity:
    def test_should_match_kpi_and_trend_for_issued(self):
        _insert_cfdi(uuid="parity-001", total=1160, subtotal=1000, impuestos=160)
        _insert_cfdi(uuid="parity-002", total=580, subtotal=500, impuestos=80)
        kpi = get_month_totals(ISSUER_ID, YM, "issued")["total_base"]
        trend = get_monthly_trend(ISSUER_ID, months=3)
        march = [t for t in trend if t["ym"] == YM]
        assert len(march) == 1
        assert abs(march[0]["ingresos"] - kpi) < 0.01

    def test_should_match_kpi_and_trend_for_received(self):
        _insert_cfdi(uuid="parity-r1", direction="received", total=2320,
                     subtotal=2000, impuestos=320)
        kpi = get_month_totals(ISSUER_ID, YM, "received")["total_base"]
        trend = get_monthly_trend(ISSUER_ID, months=3)
        march = [t for t in trend if t["ym"] == YM]
        assert len(march) == 1
        assert abs(march[0]["gastos"] - kpi) < 0.01

    def test_should_both_exclude_cancelled(self):
        _insert_cfdi(uuid="both-active", total=1000, subtotal=862.07)
        _insert_cfdi(uuid="both-cancel", total=500, subtotal=431.03, status="CANCELADO")
        kpi = get_month_totals(ISSUER_ID, YM, "issued")["total_base"]
        trend = get_monthly_trend(ISSUER_ID, months=3)
        march = [t for t in trend if t["ym"] == YM]
        assert abs(march[0]["ingresos"] - kpi) < 0.01
        assert abs(kpi - 862.07) < 0.01
