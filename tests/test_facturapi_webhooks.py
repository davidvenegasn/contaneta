"""Facturapi webhook receiver tests — signature verification, idempotency, dispatch."""
import hashlib
import hmac
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_test_db = os.environ.get("APP_DB_PATH")
if not _test_db:
    _fd, _test_db = tempfile.mkstemp(suffix=".db", prefix="test_fpi_webhook_")
    os.close(_fd)
    os.environ["APP_DB_PATH"] = _test_db
if not os.environ.get("SESSION_SECRET"):
    os.environ["SESSION_SECRET"] = "test-secret-fpi-webhook"

from starlette.testclient import TestClient

from app import app
from database import db
from services.facturapi import webhooks as fpi_webhooks

client = TestClient(app, raise_server_exceptions=False)

WEBHOOK_SECRET = "whsec_test_facturapi_abc123"


def _signed_post(body_dict: dict, *, secret: str = WEBHOOK_SECRET) -> tuple[int, dict]:
    body = json.dumps(body_dict, ensure_ascii=False).encode("utf-8")
    sig = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    r = client.post(
        "/api/webhooks/facturapi",
        content=body,
        headers={fpi_webhooks.SIGNATURE_HEADER: sig, "Content-Type": "application/json"},
    )
    try:
        return r.status_code, r.json()
    except Exception:
        return r.status_code, {}


def _unique_event(type_: str = "invoice.status_updated", **data) -> dict:
    import uuid
    return {
        "id": f"evt_{uuid.uuid4().hex[:16]}",
        "type": type_,
        "data": data or {"id": "inv_test", "status": "valid"},
    }


def test_should_return_503_when_secret_not_configured():
    with patch("routers.api.webhooks.facturapi.FACTURAPI_WEBHOOK_SECRET", ""):
        r = client.post("/api/webhooks/facturapi", content=b'{"type":"test"}')
        assert r.status_code == 503


def test_should_return_400_when_signature_missing():
    with patch("routers.api.webhooks.facturapi.FACTURAPI_WEBHOOK_SECRET", WEBHOOK_SECRET):
        r = client.post("/api/webhooks/facturapi", content=b'{"type":"test"}')
        assert r.status_code == 400


def test_should_return_400_when_signature_invalid():
    with patch("routers.api.webhooks.facturapi.FACTURAPI_WEBHOOK_SECRET", WEBHOOK_SECRET):
        r = client.post(
            "/api/webhooks/facturapi",
            content=b'{"type":"test"}',
            headers={fpi_webhooks.SIGNATURE_HEADER: "deadbeef"},
        )
        assert r.status_code == 400


def test_should_return_400_when_payload_not_json():
    with patch("routers.api.webhooks.facturapi.FACTURAPI_WEBHOOK_SECRET", WEBHOOK_SECRET):
        body = b"not-json"
        sig = hmac.new(WEBHOOK_SECRET.encode("utf-8"), body, hashlib.sha256).hexdigest()
        r = client.post(
            "/api/webhooks/facturapi",
            content=body,
            headers={fpi_webhooks.SIGNATURE_HEADER: sig},
        )
        assert r.status_code == 400


def test_should_return_400_when_event_missing_id_or_type():
    with patch("routers.api.webhooks.facturapi.FACTURAPI_WEBHOOK_SECRET", WEBHOOK_SECRET):
        status, _ = _signed_post({"type": "x", "data": {}})  # no id
        assert status == 400
        status, _ = _signed_post({"id": "evt_1", "data": {}})  # no type
        assert status == 400


def test_should_persist_event_on_first_receipt():
    with patch("routers.api.webhooks.facturapi.FACTURAPI_WEBHOOK_SECRET", WEBHOOK_SECRET):
        event = _unique_event()
        status, body = _signed_post(event)
        assert status == 200
        assert body.get("ok") is True
        assert body.get("duplicate") is not True
        conn = db()
        try:
            row = conn.execute(
                "SELECT event_id, event_type, processed_at FROM facturapi_webhook_events WHERE event_id = ?",
                (event["id"],),
            ).fetchone()
            assert row is not None
            assert row["event_type"] == event["type"]
            assert row["processed_at"] is not None
        finally:
            conn.close()


def test_should_return_duplicate_when_event_already_received():
    with patch("routers.api.webhooks.facturapi.FACTURAPI_WEBHOOK_SECRET", WEBHOOK_SECRET):
        event = _unique_event()
        first_status, _ = _signed_post(event)
        assert first_status == 200
        second_status, second_body = _signed_post(event)
        assert second_status == 200
        assert second_body.get("duplicate") is True


def test_should_dispatch_invoice_cancellation_accepted():
    """Posting a cancellation-accepted event should mark the matching invoice as canceled."""
    conn = db()
    try:
        cur = conn.execute(
            """INSERT INTO invoices
               (issuer_id, status, currency, payment_form, payment_method, cfdi_use,
                customer_rfc, customer_legal_name, customer_zip, customer_tax_system,
                facturapi_invoice_id, total, cancelled)
               VALUES (1, 'valid', 'MXN', '03', 'PUE', 'G03',
                       'XAXX010101000', 'TEST', '64000', '616',
                       'inv_test_cancel_42', 100.0, 0)""",
        )
        invoice_pk = cur.lastrowid
        conn.commit()
    finally:
        conn.close()

    with patch("routers.api.webhooks.facturapi.FACTURAPI_WEBHOOK_SECRET", WEBHOOK_SECRET):
        event = _unique_event(
            type_="invoice.cancellation_accepted",
            id="inv_test_cancel_42",
            status="canceled",
        )
        status, _ = _signed_post(event)
        assert status == 200

    conn = db()
    try:
        row = conn.execute(
            "SELECT status, cancelled FROM invoices WHERE id = ?",
            (invoice_pk,),
        ).fetchone()
        assert row is not None
        assert row["status"] == "canceled"
        assert row["cancelled"] == 1
    finally:
        conn.close()


def test_should_dispatch_manifest_signed_updates_issuer():
    """manifest.signed should set manifest_signed_at on the matching issuer."""
    conn = db()
    try:
        cur = conn.execute(
            "INSERT INTO issuers (rfc, razon_social, active, facturapi_org_id) VALUES (?, ?, 1, ?)",
            ("TEST010101AAA", "TEST MANIFEST", "org_test_signed_42"),
        )
        issuer_pk = cur.lastrowid
        conn.commit()
    finally:
        conn.close()

    with patch("routers.api.webhooks.facturapi.FACTURAPI_WEBHOOK_SECRET", WEBHOOK_SECRET):
        event = _unique_event(
            type_="manifest.signed",
            organization_id="org_test_signed_42",
        )
        status, _ = _signed_post(event)
        assert status == 200

    conn = db()
    try:
        row = conn.execute(
            "SELECT manifest_signed_at FROM issuers WHERE id = ?",
            (issuer_pk,),
        ).fetchone()
        assert row is not None
        assert row["manifest_signed_at"] is not None
    finally:
        conn.close()


def test_verify_signature_constant_time():
    """verify_signature must reject mismatched signatures even when length matches."""
    body = b'{"hello":"world"}'
    secret = "s3cret"
    good = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    assert fpi_webhooks.verify_signature(body, good, secret) is True
    # Same length, wrong value
    bad = "0" * len(good)
    assert fpi_webhooks.verify_signature(body, bad, secret) is False
    # Empty header
    assert fpi_webhooks.verify_signature(body, "", secret) is False
    # Empty secret
    assert fpi_webhooks.verify_signature(body, good, "") is False
