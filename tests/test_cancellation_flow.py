"""Tests for cancellation + substitution flow."""
import uuid as uuid_mod
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from database import db, db_rows
from services.cancellation.log import insert_log
from services.cancellation.service import cancel_invoice, substitute_and_cancel
from services.cancellation.status import _map_sat_status, poll_pending_cancellations
from services.cancellation.types import CancellationStatus, Motivo


# ---- Helpers ----

def _create_test_issuer(*, org_id="org_test_123"):
    """Create a minimal issuer for testing."""
    conn = db()
    cur = conn.execute(
        """INSERT INTO issuers (rfc, razon_social, active, facturapi_org_id, created_at)
           VALUES (?, ?, 1, ?, datetime('now'))""",
        (f"TST{uuid_mod.uuid4().hex[:9].upper()}", "Test Issuer SA", org_id),
    )
    issuer_id = cur.lastrowid
    conn.commit()
    conn.close()
    return issuer_id


def _create_test_invoice(issuer_id, *, total=1000.0, uuid_val=None, facturapi_id=None):
    """Create a minimal invoice record for testing."""
    test_uuid = uuid_val or str(uuid_mod.uuid4())
    test_fapi_id = facturapi_id or f"fapi_{uuid_mod.uuid4().hex[:8]}"
    conn = db()
    cur = conn.execute(
        """INSERT INTO invoices (issuer_id, uuid, total, facturapi_invoice_id,
                                customer_rfc, customer_legal_name, customer_zip, customer_tax_system,
                                currency, payment_form, payment_method, cfdi_use,
                                status, cancelled, created_at)
           VALUES (?, ?, ?, ?, 'XAXX010101000', 'Test Customer', '06600', '601',
                   'MXN', '01', 'PUE', 'G03', 'active', 0, datetime('now'))""",
        (issuer_id, test_uuid, total, test_fapi_id),
    )
    invoice_id = cur.lastrowid
    # Also create sat_cfdi record
    conn.execute(
        """INSERT INTO sat_cfdi (issuer_id, direction, uuid, status, fecha_emision,
                                 rfc_emisor, nombre_emisor, rfc_receptor, nombre_receptor,
                                 total, moneda, tipo_comprobante, updated_at)
           VALUES (?, 'issued', ?, 'V', datetime('now'),
                   'TST000000001', 'Test Issuer', 'XAXX010101000', 'Test Customer',
                   ?, 'MXN', 'I', datetime('now'))
           ON CONFLICT(issuer_id, direction, uuid) DO NOTHING""",
        (issuer_id, test_uuid, total),
    )
    conn.commit()
    conn.close()
    return {"id": invoice_id, "uuid": test_uuid, "facturapi_id": test_fapi_id, "total": total}


# ---- Types tests ----

def test_motivo_values():
    assert Motivo.ERROR_CON_RELACION.value == "01"
    assert Motivo.NO_OPERACION.value == "03"


def test_cancellation_status_values():
    assert CancellationStatus.PENDING.value == "pending"
    assert CancellationStatus.ACCEPTED.value == "accepted"
    assert CancellationStatus.EXPIRED.value == "expired"


# ---- Log tests ----

def test_insert_log_returns_id():
    log_id = insert_log(
        issuer_id=999, user_id=1, cfdi_uuid="test-uuid-log",
        motivo="03", event="requested",
    )
    assert isinstance(log_id, int)
    assert log_id > 0
    rows = db_rows("SELECT * FROM cancellation_log WHERE id = ?", (log_id,))
    assert len(rows) == 1
    assert rows[0]["cfdi_uuid"] == "test-uuid-log"
    assert rows[0]["event"] == "requested"


# ---- Service tests ----

def test_should_raise_when_motivo_01_without_substitute():
    with pytest.raises(ValueError, match="sustitución"):
        cancel_invoice(
            issuer_id=999, user_id=1, cfdi_uuid="nonexistent",
            motivo=Motivo.ERROR_CON_RELACION, substitute_uuid=None,
        )


def test_should_raise_when_invoice_not_found():
    issuer_id = _create_test_issuer()
    with pytest.raises(ValueError, match="no encontrado"):
        cancel_invoice(
            issuer_id=issuer_id, user_id=1, cfdi_uuid="nonexistent-uuid",
            motivo=Motivo.NO_OPERACION,
        )


def test_should_raise_when_no_facturapi_id():
    issuer_id = _create_test_issuer()
    test_uuid = str(uuid_mod.uuid4())
    conn = db()
    conn.execute(
        """INSERT INTO invoices (issuer_id, uuid, total, facturapi_invoice_id,
                                customer_rfc, customer_legal_name, customer_zip, customer_tax_system,
                                currency, payment_form, payment_method, cfdi_use,
                                status, cancelled, created_at)
           VALUES (?, ?, 100, NULL, 'XAXX010101000', 'Test', '06600', '601',
                   'MXN', '01', 'PUE', 'G03', 'active', 0, datetime('now'))""",
        (issuer_id, test_uuid),
    )
    conn.commit()
    conn.close()
    with pytest.raises(ValueError, match="sin ID"):
        cancel_invoice(
            issuer_id=issuer_id, user_id=1, cfdi_uuid=test_uuid,
            motivo=Motivo.NO_OPERACION,
        )


@patch("services.cancellation.service.facturapi_cancel")
def test_should_cancel_accepted_when_under_5000(mock_cancel):
    mock_cancel.return_value = {"status": "canceled", "cancellation_status": "none"}
    issuer_id = _create_test_issuer()
    inv = _create_test_invoice(issuer_id, total=1000.0)
    result = cancel_invoice(
        issuer_id=issuer_id, user_id=1, cfdi_uuid=inv["uuid"],
        motivo=Motivo.NO_OPERACION,
    )
    assert result["status"] == "accepted"
    assert result["requires_receptor_acceptance"] is False
    # Verify DB state
    rows = db_rows(
        "SELECT cancellation_status, cancellation_motivo FROM sat_cfdi WHERE issuer_id = ? AND uuid = ?",
        (issuer_id, inv["uuid"]),
    )
    assert rows[0]["cancellation_status"] == "accepted"
    assert rows[0]["cancellation_motivo"] == "03"


@patch("services.cancellation.service.facturapi_cancel")
def test_should_cancel_pending_when_over_5000(mock_cancel):
    mock_cancel.return_value = {"status": "active", "cancellation_status": "pending"}
    issuer_id = _create_test_issuer()
    inv = _create_test_invoice(issuer_id, total=10000.0)
    result = cancel_invoice(
        issuer_id=issuer_id, user_id=1, cfdi_uuid=inv["uuid"],
        motivo=Motivo.NO_OPERACION,
    )
    assert result["status"] == "pending"
    assert result["requires_receptor_acceptance"] is True


@patch("services.cancellation.service.facturapi_cancel")
def test_should_cancel_with_substitution(mock_cancel):
    mock_cancel.return_value = {"status": "canceled", "cancellation_status": "none"}
    issuer_id = _create_test_issuer()
    inv = _create_test_invoice(issuer_id, total=2000.0)
    sub_uuid = str(uuid_mod.uuid4())
    result = cancel_invoice(
        issuer_id=issuer_id, user_id=1, cfdi_uuid=inv["uuid"],
        motivo=Motivo.ERROR_CON_RELACION, substitute_uuid=sub_uuid,
    )
    assert result["status"] == "accepted"
    # Verify substitution UUID stored
    rows = db_rows(
        "SELECT cancellation_substitute_uuid FROM sat_cfdi WHERE issuer_id = ? AND uuid = ?",
        (issuer_id, inv["uuid"]),
    )
    assert rows[0]["cancellation_substitute_uuid"] == sub_uuid


@patch("services.cancellation.service.facturapi_cancel")
def test_should_log_failed_on_facturapi_error(mock_cancel):
    from facturapi_client import FacturapiError
    mock_cancel.side_effect = FacturapiError("API Error 500")
    issuer_id = _create_test_issuer()
    inv = _create_test_invoice(issuer_id, total=500.0)
    with pytest.raises(FacturapiError):
        cancel_invoice(
            issuer_id=issuer_id, user_id=1, cfdi_uuid=inv["uuid"],
            motivo=Motivo.NO_OPERACION,
        )
    logs = db_rows(
        "SELECT event, error_message FROM cancellation_log WHERE cfdi_uuid = ? ORDER BY id",
        (inv["uuid"],),
    )
    assert any(l["event"] == "failed" for l in logs)


# ---- substitute_and_cancel tests ----

@patch("services.cancellation.service.facturapi_cancel")
@patch("facturapi_client.create_invoice")
def test_substitute_and_cancel_full_flow(mock_create, mock_cancel):
    new_uuid = str(uuid_mod.uuid4())
    mock_create.return_value = {"uuid": new_uuid, "id": "fapi_new"}
    mock_cancel.return_value = {"status": "canceled", "cancellation_status": "none"}

    issuer_id = _create_test_issuer()
    inv = _create_test_invoice(issuer_id, total=3000.0)

    result = substitute_and_cancel(
        issuer_id=issuer_id, user_id=1,
        original_uuid=inv["uuid"],
        new_cfdi_payload={"type": "I", "customer": {}, "items": []},
    )
    assert result["substitute_uuid"] == new_uuid.lower()
    assert result["cancellation_status"] == "accepted"
    # Verify TipoRelacion 04 was injected
    call_payload = mock_create.call_args[0][2]
    assert call_payload["related_documents"][0]["relationship"] == "04"


@patch("facturapi_client.create_invoice")
def test_substitute_and_cancel_preserves_uuid_on_cancel_fail(mock_create):
    from facturapi_client import FacturapiError

    new_uuid = str(uuid_mod.uuid4())
    mock_create.return_value = {"uuid": new_uuid, "id": "fapi_new2"}

    issuer_id = _create_test_issuer()
    inv = _create_test_invoice(issuer_id, total=2000.0)

    with patch("services.cancellation.service.facturapi_cancel", side_effect=FacturapiError("fail")):
        result = substitute_and_cancel(
            issuer_id=issuer_id, user_id=1,
            original_uuid=inv["uuid"],
            new_cfdi_payload={"type": "I"},
        )
    assert result["substitute_uuid"] == new_uuid.lower()
    assert result["cancellation_status"] == "failed"
    assert "error" in result


# ---- Status polling tests ----

def test_map_sat_status_canceled():
    assert _map_sat_status("canceled", None) == CancellationStatus.ACCEPTED


def test_map_sat_status_rejected():
    assert _map_sat_status("rejected", None) == CancellationStatus.REJECTED


def test_map_sat_status_expired_after_72h():
    old = (datetime.now(timezone.utc) - timedelta(hours=73)).isoformat()
    assert _map_sat_status("active", old) == CancellationStatus.EXPIRED


def test_map_sat_status_still_pending():
    recent = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    assert _map_sat_status("active", recent) == CancellationStatus.PENDING


# ---- Migration verification ----

def test_cancellation_log_table_exists():
    rows = db_rows("SELECT name FROM sqlite_master WHERE type='table' AND name='cancellation_log'")
    assert len(rows) == 1


def test_sat_cfdi_has_cancellation_columns():
    cols = db_rows("PRAGMA table_info(sat_cfdi)")
    col_names = [c["name"] for c in cols]
    for expected in ["cancellation_status", "cancellation_motivo", "cancellation_substitute_uuid",
                     "cancellation_requested_at", "cancellation_finalized_at", "cancellation_requested_by_user_id"]:
        assert expected in col_names, f"Missing column: {expected}"


# ---- facturapi_client.cancel_invoice substitution param ----

def test_facturapi_cancel_accepts_substitution_param():
    """Verify cancel_invoice signature accepts substitution kwarg."""
    import inspect
    from facturapi_client import cancel_invoice as fapi_cancel
    sig = inspect.signature(fapi_cancel)
    assert "substitution" in sig.parameters
