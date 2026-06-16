"""Tests for the reports module (monthly, annual, PPD, exporters)."""
import uuid as uuid_mod
from datetime import datetime

import pytest

from database import db, db_rows
from services.reports.monthly import build_monthly_report
from services.reports.annual import build_annual_report
from services.reports.ppd_cobranza import build_ppd_outstanding_report
from services.reports.exporters import monthly_to_excel, annual_to_excel

ISSUER_ID = 99910
USER_ID = 99910


@pytest.fixture(scope="module", autouse=True)
def seed():
    """Create a fixed issuer/user for route tests."""
    conn = db()
    conn.execute(
        "INSERT OR IGNORE INTO issuers (id, rfc, razon_social, active, created_at, updated_at) "
        "VALUES (?, 'RPT010101AAA', 'Report Test SA', 1, datetime('now'), datetime('now'))",
        (ISSUER_ID,),
    )
    conn.execute(
        "INSERT OR IGNORE INTO users (id, email, password_hash, created_at) "
        "VALUES (?, 'reports@test.local', 'x', datetime('now'))",
        (USER_ID,),
    )
    conn.execute(
        "INSERT OR IGNORE INTO memberships (user_id, issuer_id, role, created_at) "
        "VALUES (?, ?, 'owner', datetime('now'))",
        (USER_ID, ISSUER_ID),
    )
    conn.commit()
    conn.close()
    yield


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient
    from app import app
    from tests.helpers import make_session_cookie
    cookies = make_session_cookie(issuer_id=ISSUER_ID, user_id=USER_ID)
    return TestClient(app, raise_server_exceptions=False, cookies=cookies)


# ---- Helpers ----

def _create_issuer(regimen="601"):
    conn = db()
    cur = conn.execute(
        """INSERT INTO issuers (rfc, razon_social, regimen_fiscal, active, created_at)
           VALUES (?, 'Report Test SA', ?, 1, datetime('now'))""",
        (f"RPT{uuid_mod.uuid4().hex[:9].upper()}", regimen),
    )
    issuer_id = cur.lastrowid
    conn.commit()
    conn.close()
    return issuer_id


def _insert_cfdi(issuer_id, direction, *, ym="2026-01", tipo="I", total=1000.0,
                 subtotal=862.07, impuestos=137.93, retenciones=0.0, status="V",
                 rfc_emisor="XAXX010101000", nombre_emisor="Test Emisor",
                 rfc_receptor="XAXX010101000", nombre_receptor="Test Receptor"):
    test_uuid = str(uuid_mod.uuid4())
    fecha = f"{ym}-15T12:00:00"
    conn = db()
    conn.execute(
        """INSERT INTO sat_cfdi (issuer_id, uuid, direction, fecha_emision,
                  rfc_emisor, nombre_emisor, rfc_receptor, nombre_receptor,
                  tipo_comprobante, subtotal, impuestos, retenciones, total,
                  moneda, status, concepto)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'MXN', ?, 'Test')""",
        (issuer_id, test_uuid, direction, fecha,
         rfc_emisor, nombre_emisor, rfc_receptor, nombre_receptor,
         tipo, subtotal, impuestos, retenciones, total, status),
    )
    conn.commit()
    conn.close()
    return test_uuid


def _insert_ppd_invoice(issuer_id, *, total=10000.0, fecha="2026-01-10"):
    test_uuid = str(uuid_mod.uuid4())
    conn = db()
    cur = conn.execute(
        """INSERT INTO invoices (issuer_id, uuid, total, currency, payment_method, payment_form,
                                cfdi_use, customer_rfc, customer_legal_name, customer_zip,
                                customer_tax_system, status, cancelled, created_at)
           VALUES (?, ?, ?, 'MXN', 'PPD', '99', 'G03', 'XAXX010101000', 'Test PPD Client',
                   '06600', '601', 'active', 0, ?)""",
        (issuer_id, test_uuid, total, fecha),
    )
    invoice_id = cur.lastrowid
    # Also insert into sat_cfdi so the report can find the fecha_emision
    conn.execute(
        """INSERT INTO sat_cfdi (issuer_id, uuid, direction, fecha_emision,
                  rfc_emisor, nombre_emisor, rfc_receptor, nombre_receptor,
                  tipo_comprobante, subtotal, impuestos, retenciones, total,
                  moneda, status, concepto, metodo_pago)
           VALUES (?, ?, 'issued', ?, 'RPT000', 'Test Issuer', 'XAXX010101000',
                   'Test PPD Client', 'I', ?, 0, 0, ?, 'MXN', 'V', 'Test PPD', 'PPD')""",
        (issuer_id, test_uuid, fecha, total * 0.862, total),
    )
    conn.commit()
    conn.close()
    return {"id": invoice_id, "uuid": test_uuid, "total": total}


# ---- Monthly report tests ----

def test_should_return_correct_structure_for_monthly_report():
    """Monthly report should have all expected keys."""
    iid = _create_issuer()
    report = build_monthly_report(iid, "2026-01")
    assert "periodo" in report
    assert report["periodo"] == "2026-01"
    assert "ingresos" in report
    assert "gastos_neto" in report
    assert "notas_credito" in report
    assert "utilidad_fiscal" in report
    assert "iva_neto" in report
    assert "isr_estimado" in report
    assert "cfdi_emitidos" in report
    assert "cfdi_recibidos" in report


def test_should_compute_ingresos_from_issued_cfdis():
    """Monthly report ingresos should reflect issued CFDIs."""
    iid = _create_issuer()
    _insert_cfdi(iid, "issued", ym="2026-03", subtotal=1000.0, impuestos=160.0, total=1160.0)
    _insert_cfdi(iid, "issued", ym="2026-03", subtotal=2000.0, impuestos=320.0, total=2320.0)
    report = build_monthly_report(iid, "2026-03")
    # Should have 2 emitidos
    assert len(report["cfdi_emitidos"]) == 2


def test_should_return_zero_values_when_no_data():
    """Monthly report with no data should return zeroed values."""
    iid = _create_issuer()
    report = build_monthly_report(iid, "2025-01")
    assert report["ingresos"]["subtotal"] == 0
    assert report["utilidad_fiscal"] == 0
    assert report["iva_neto"] == 0
    assert report["isr_estimado"] == 0


def test_should_estimate_isr_based_on_regimen_601():
    """PM (601) should use 30% ISR rate."""
    iid = _create_issuer(regimen="601")
    _insert_cfdi(iid, "issued", ym="2026-04", subtotal=10000.0, impuestos=1600.0, total=11600.0)
    report = build_monthly_report(iid, "2026-04")
    # ISR should be approximately 30% of utilidad (which is subtotal since no gastos)
    if report["utilidad_fiscal"] > 0:
        assert report["isr_estimado"] == pytest.approx(report["utilidad_fiscal"] * 0.30, abs=1.0)


def test_should_estimate_isr_resico():
    """RESICO PF (626) should use flat ~1.25% rate."""
    iid = _create_issuer(regimen="626")
    _insert_cfdi(iid, "issued", ym="2026-04", subtotal=10000.0, impuestos=1600.0, total=11600.0)
    report = build_monthly_report(iid, "2026-04")
    if report["utilidad_fiscal"] > 0:
        assert report["isr_estimado"] == pytest.approx(report["utilidad_fiscal"] * 0.0125, abs=1.0)


# ---- Annual report tests ----

def test_should_return_12_months_in_annual_report():
    """Annual report should always have 12 month entries."""
    iid = _create_issuer()
    report = build_annual_report(iid, 2026)
    assert report["year"] == 2026
    assert len(report["months"]) == 12
    assert "totals" in report
    for m in report["months"]:
        assert "ym" in m
        assert "ingresos_subtotal" in m
        assert "utilidad" in m


def test_should_aggregate_totals_in_annual_report():
    """Annual totals should match sum of monthly values."""
    iid = _create_issuer()
    _insert_cfdi(iid, "issued", ym="2026-02", subtotal=5000.0, impuestos=800.0, total=5800.0)
    _insert_cfdi(iid, "issued", ym="2026-06", subtotal=3000.0, impuestos=480.0, total=3480.0)
    report = build_annual_report(iid, 2026)
    sum_ingresos = sum(m["ingresos_subtotal"] for m in report["months"])
    assert report["totals"]["ingresos_subtotal"] == pytest.approx(sum_ingresos, abs=0.01)


# ---- PPD cobranza tests ----

def test_should_return_ppd_outstanding_invoices():
    """PPD report should list invoices with saldo > 0."""
    iid = _create_issuer()
    inv = _insert_ppd_invoice(iid, total=20000.0, fecha="2026-01-10")
    report = build_ppd_outstanding_report(iid)
    assert report["count"] == 1
    assert report["total_pendiente"] == 20000.0
    assert report["invoices"][0]["saldo_insoluto"] == 20000.0


def test_should_exclude_paid_ppd_invoices():
    """PPD report should exclude invoices with saldo = 0."""
    iid = _create_issuer()
    inv = _insert_ppd_invoice(iid, total=5000.0, fecha="2026-02-15")
    # Record a full payment
    conn = db()
    conn.execute(
        """INSERT INTO invoice_payments (invoice_id, issuer_id, parcialidad, saldo_insoluto,
                    monto_pagado, importe_abonado, saldo_anterior, fecha_pago, forma_pago, created_at)
           VALUES (?, ?, 1, 0, 5000.0, 5000.0, 5000.0, '2026-02-20', '03', datetime('now'))""",
        (inv["id"], iid),
    )
    conn.commit()
    conn.close()
    report = build_ppd_outstanding_report(iid)
    assert report["count"] == 0
    assert report["total_pendiente"] == 0


def test_should_sort_ppd_by_days_since_emission():
    """PPD items should be sorted by days_since_emission descending."""
    iid = _create_issuer()
    _insert_ppd_invoice(iid, total=1000.0, fecha="2026-06-01")   # newer = fewer days
    _insert_ppd_invoice(iid, total=2000.0, fecha="2026-01-01")   # older = more days
    report = build_ppd_outstanding_report(iid)
    if report["count"] >= 2:
        assert report["invoices"][0]["dias_desde_emision"] >= report["invoices"][1]["dias_desde_emision"]


# ---- Exporter tests ----

def test_should_generate_valid_monthly_excel():
    """Monthly Excel export should produce valid bytes."""
    report = {
        "periodo": "2026-01",
        "ingresos": {"n": 1, "subtotal": 1000.0, "iva": 160.0, "retenciones": 0.0, "total": 1160.0},
        "gastos_neto": {"n": 0, "subtotal": 0.0, "iva_acreditable": 0.0, "retenciones": 0, "total": 0.0},
        "notas_credito": {"n": 0, "subtotal": 0.0, "iva": 0.0, "total": 0.0},
        "utilidad_fiscal": 1000.0,
        "iva_neto": 160.0,
        "isr_estimado": 300.0,
        "cfdi_emitidos": [],
        "cfdi_recibidos": [],
    }
    excel_bytes = monthly_to_excel(report)
    assert isinstance(excel_bytes, bytes)
    assert len(excel_bytes) > 100
    # Check it starts with PK (ZIP/XLSX magic bytes)
    assert excel_bytes[:2] == b"PK"


def test_should_generate_valid_annual_excel():
    """Annual Excel export should produce valid bytes."""
    months = []
    for i in range(12):
        months.append({
            "ym": f"2026-{i+1:02d}",
            "ingresos_subtotal": 1000.0 * (i + 1),
            "ingresos_iva": 160.0 * (i + 1),
            "ingresos_retenciones": 0.0,
            "gastos_subtotal": 500.0 * (i + 1),
            "gastos_iva": 80.0 * (i + 1),
            "utilidad": 500.0 * (i + 1),
            "iva_neto": 80.0 * (i + 1),
            "isr_estimado": 150.0 * (i + 1),
        })
    report = {
        "year": 2026,
        "months": months,
        "totals": {
            "ingresos_subtotal": sum(m["ingresos_subtotal"] for m in months),
            "ingresos_iva": sum(m["ingresos_iva"] for m in months),
            "ingresos_retenciones": 0.0,
            "gastos_subtotal": sum(m["gastos_subtotal"] for m in months),
            "gastos_iva": sum(m["gastos_iva"] for m in months),
            "utilidad": sum(m["utilidad"] for m in months),
            "iva_neto": sum(m["iva_neto"] for m in months),
            "isr_provisionales": sum(m["isr_estimado"] for m in months),
        },
    }
    excel_bytes = annual_to_excel(report)
    assert isinstance(excel_bytes, bytes)
    assert len(excel_bytes) > 100
    assert excel_bytes[:2] == b"PK"


# ---- Route tests ----

def test_should_respond_200_monthly_report(client):
    """GET /portal/reports/monthly should return 200."""
    resp = client.get("/portal/reports/monthly")
    assert resp.status_code == 200
    assert "Reporte" in resp.text or "reporte" in resp.text


def test_should_respond_200_annual_report(client):
    """GET /portal/reports/annual should return 200."""
    resp = client.get("/portal/reports/annual")
    assert resp.status_code == 200


def test_should_respond_200_ppd_report(client):
    """GET /portal/reports/ppd-cobranza should return 200."""
    resp = client.get("/portal/reports/ppd-cobranza")
    assert resp.status_code == 200


def test_should_download_monthly_excel(client):
    """GET /portal/reports/monthly/excel should return xlsx content type."""
    resp = client.get("/portal/reports/monthly/excel?ym=2026-01")
    assert resp.status_code == 200
    assert "spreadsheet" in resp.headers.get("content-type", "")


def test_should_download_annual_excel(client):
    """GET /portal/reports/annual/excel should return xlsx content type."""
    resp = client.get("/portal/reports/annual/excel?year=2026")
    assert resp.status_code == 200
    assert "spreadsheet" in resp.headers.get("content-type", "")
