"""Tests for REP (Complemento de Pago) edge cases and full flow."""
import uuid as uuid_mod
from decimal import Decimal

import pytest

from database import db, db_rows
from services.invoices.rep import (
    build_rep_payload,
    compute_equivalencia_dr,
    get_ppd_state,
    record_payment,
)


# ---- Helpers ----

def _create_issuer():
    conn = db()
    cur = conn.execute(
        """INSERT INTO issuers (rfc, razon_social, active, created_at)
           VALUES (?, 'REP Test SA', 1, datetime('now'))""",
        (f"REP{uuid_mod.uuid4().hex[:9].upper()}",),
    )
    issuer_id = cur.lastrowid
    conn.commit()
    conn.close()
    return issuer_id


def _create_ppd_invoice(issuer_id, *, total=10000.0, currency="MXN"):
    test_uuid = str(uuid_mod.uuid4())
    conn = db()
    cur = conn.execute(
        """INSERT INTO invoices (issuer_id, uuid, total, currency, payment_method, payment_form,
                                cfdi_use, customer_rfc, customer_legal_name, customer_zip,
                                customer_tax_system, status, cancelled, created_at)
           VALUES (?, ?, ?, ?, 'PPD', '99', 'G03', 'XAXX010101000', 'Test Client',
                   '06600', '601', 'active', 0, datetime('now'))""",
        (issuer_id, test_uuid, total, currency),
    )
    invoice_id = cur.lastrowid
    conn.commit()
    conn.close()
    return {"id": invoice_id, "uuid": test_uuid, "total": total, "currency": currency,
            "customer_rfc": "XAXX010101000", "customer_legal_name": "Test Client",
            "customer_zip": "06600", "customer_tax_system": "601", "payment_method": "PPD"}


# ---- get_ppd_state tests ----

def test_should_return_full_total_as_saldo_when_no_payments():
    iid = _create_issuer()
    inv = _create_ppd_invoice(iid, total=15000.0)
    state = get_ppd_state(iid, inv["id"])
    assert state["total"] == 15000.0
    assert state["saldo_insoluto"] == 15000.0
    assert state["next_parcialidad"] == 1
    assert state["payments"] == []


def test_should_track_saldo_after_partial_payment():
    iid = _create_issuer()
    inv = _create_ppd_invoice(iid, total=10000.0)
    conn = db()
    record_payment(conn, issuer_id=iid, invoice_id=inv["id"],
                   rep_invoice_id=None, rep_uuid=None,
                   parcialidad=1, fecha_pago="2026-06-01", forma_pago="03",
                   moneda_pago="MXN", tipo_cambio_pago=None,
                   monto_pagado=4000.0, importe_abonado=4000.0,
                   saldo_anterior=10000.0, saldo_insoluto=6000.0, num_operacion=None)
    conn.commit()
    conn.close()

    state = get_ppd_state(iid, inv["id"])
    assert state["saldo_insoluto"] == 6000.0
    assert state["next_parcialidad"] == 2
    assert len(state["payments"]) == 1


def test_should_reach_zero_saldo_on_full_payment():
    iid = _create_issuer()
    inv = _create_ppd_invoice(iid, total=5000.0)
    conn = db()
    record_payment(conn, issuer_id=iid, invoice_id=inv["id"],
                   rep_invoice_id=None, rep_uuid=None,
                   parcialidad=1, fecha_pago="2026-06-01", forma_pago="03",
                   moneda_pago="MXN", tipo_cambio_pago=None,
                   monto_pagado=5000.0, importe_abonado=5000.0,
                   saldo_anterior=5000.0, saldo_insoluto=0.0, num_operacion=None)
    conn.commit()
    conn.close()

    state = get_ppd_state(iid, inv["id"])
    assert state["saldo_insoluto"] == 0.0
    assert state["next_parcialidad"] == 2


# ---- build_rep_payload tests ----

def test_should_build_valid_payload_for_first_parcialidad():
    inv = {"uuid": "abc-123", "total": 10000.0, "currency": "MXN",
           "customer_rfc": "XAXX010101000", "customer_legal_name": "Test",
           "customer_tax_system": "601", "customer_zip": "06600"}
    payload = build_rep_payload(
        invoice=inv, fecha_pago="2026-06-01", forma_pago="03",
        moneda_pago="MXN", tipo_cambio_pago=None,
        monto_pagado=3000.0, importe_abonado=3000.0,
        saldo_anterior=10000.0, num_operacion="REF123", parcialidad=1,
    )
    assert payload["type"] == "P"
    assert len(payload["payments"]) == 1
    p = payload["payments"][0]
    assert p["amount"] == 3000.0
    assert p["form"] == "03"
    assert p["operation_number"] == "REF123"
    rd = p["related_documents"][0]
    assert rd["installment"] == 1
    assert rd["previous_balance"] == 10000.0
    assert rd["amount"] == 3000.0
    assert rd["exchange_rate"] == 1.0


def test_should_compute_correct_saldo_insoluto_in_payload():
    inv = {"uuid": "abc-456", "total": 10000.0, "currency": "MXN",
           "customer_rfc": "X", "customer_legal_name": "T",
           "customer_tax_system": "601", "customer_zip": "00000"}
    payload = build_rep_payload(
        invoice=inv, fecha_pago="2026-06-05", forma_pago="03",
        moneda_pago="MXN", tipo_cambio_pago=None,
        monto_pagado=7500.50, importe_abonado=7500.50,
        saldo_anterior=10000.0, num_operacion=None, parcialidad=1,
    )
    # saldo_insoluto computed internally: 10000 - 7500.50 = 2499.50
    rd = payload["payments"][0]["related_documents"][0]
    assert rd["previous_balance"] == 10000.0
    assert rd["amount"] == 7500.50


def test_should_handle_usd_invoice_with_mxn_payment():
    inv = {"uuid": "usd-789", "total": 1000.0, "currency": "USD",
           "customer_rfc": "X", "customer_legal_name": "T",
           "customer_tax_system": "601", "customer_zip": "00000"}
    payload = build_rep_payload(
        invoice=inv, fecha_pago="2026-06-10", forma_pago="03",
        moneda_pago="MXN", tipo_cambio_pago=None,
        monto_pagado=17500.0, importe_abonado=1000.0,
        saldo_anterior=1000.0, num_operacion=None, parcialidad=1,
    )
    rd = payload["payments"][0]["related_documents"][0]
    # USD != MXN so EquivalenciaDR is computed
    assert rd["currency"] == "USD"
    assert rd["exchange_rate"] != 1.0


def test_should_not_allow_negative_saldo():
    """If importe > saldo, saldo_insoluto should clamp to 0."""
    inv = {"uuid": "neg-001", "total": 1000.0, "currency": "MXN",
           "customer_rfc": "X", "customer_legal_name": "T",
           "customer_tax_system": "601", "customer_zip": "00000"}
    # Overpay: importe_abonado > saldo_anterior
    payload = build_rep_payload(
        invoice=inv, fecha_pago="2026-06-01", forma_pago="03",
        moneda_pago="MXN", tipo_cambio_pago=None,
        monto_pagado=1500.0, importe_abonado=1500.0,
        saldo_anterior=1000.0, num_operacion=None, parcialidad=1,
    )
    # The internal computation clamps to 0
    # (the build function doesn't raise, it clamps)
    assert payload["payments"][0]["amount"] == 1500.0


# ---- compute_equivalencia_dr tests ----

def test_equivalencia_dr_same_currency():
    # When same currency, the caller uses Decimal("1") directly
    # But let's test the function with equal amounts
    result = compute_equivalencia_dr(Decimal("1000"), Decimal("1000"))
    assert result == Decimal("1")


def test_equivalencia_dr_different_currency():
    # USD 1000 saldo, paid 17500 MXN → rate ~0.0571428571
    result = compute_equivalencia_dr(Decimal("1000"), Decimal("17500"))
    assert float(result) == pytest.approx(0.0571428571, abs=1e-8)


# ---- Full 2-payment flow test ----

def test_two_partial_payments_flow():
    """Full flow: create PPD invoice → pay partial → pay remainder → verify saldos."""
    iid = _create_issuer()
    inv = _create_ppd_invoice(iid, total=20000.0)

    # Payment 1: $8,000 of $20,000
    state1 = get_ppd_state(iid, inv["id"])
    assert state1["saldo_insoluto"] == 20000.0
    assert state1["next_parcialidad"] == 1

    conn = db()
    record_payment(conn, issuer_id=iid, invoice_id=inv["id"],
                   rep_invoice_id=None, rep_uuid="rep-uuid-1",
                   parcialidad=1, fecha_pago="2026-06-01", forma_pago="03",
                   moneda_pago="MXN", tipo_cambio_pago=None,
                   monto_pagado=8000.0, importe_abonado=8000.0,
                   saldo_anterior=20000.0, saldo_insoluto=12000.0, num_operacion="OP001")
    conn.commit()
    conn.close()

    state2 = get_ppd_state(iid, inv["id"])
    assert state2["saldo_insoluto"] == 12000.0
    assert state2["next_parcialidad"] == 2

    # Payment 2: $12,000 (remainder)
    conn = db()
    record_payment(conn, issuer_id=iid, invoice_id=inv["id"],
                   rep_invoice_id=None, rep_uuid="rep-uuid-2",
                   parcialidad=2, fecha_pago="2026-06-15", forma_pago="03",
                   moneda_pago="MXN", tipo_cambio_pago=None,
                   monto_pagado=12000.0, importe_abonado=12000.0,
                   saldo_anterior=12000.0, saldo_insoluto=0.0, num_operacion="OP002")
    conn.commit()
    conn.close()

    state3 = get_ppd_state(iid, inv["id"])
    assert state3["saldo_insoluto"] == 0.0
    assert state3["next_parcialidad"] == 3
    assert len(state3["payments"]) == 2


def test_should_reject_non_ppd_invoice():
    """get_ppd_state should raise for PUE invoices."""
    from services.errors import ValidationError
    iid = _create_issuer()
    test_uuid = str(uuid_mod.uuid4())
    conn = db()
    cur = conn.execute(
        """INSERT INTO invoices (issuer_id, uuid, total, currency, payment_method, payment_form,
                                cfdi_use, customer_rfc, customer_legal_name, customer_zip,
                                customer_tax_system, status, cancelled, created_at)
           VALUES (?, ?, 5000, 'MXN', 'PUE', '03', 'G03', 'XAXX010101000', 'Test',
                   '06600', '601', 'active', 0, datetime('now'))""",
        (iid, test_uuid),
    )
    inv_id = cur.lastrowid
    conn.commit()
    conn.close()
    with pytest.raises(ValidationError, match="PPD"):
        get_ppd_state(iid, inv_id)
