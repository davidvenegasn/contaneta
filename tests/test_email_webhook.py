"""Test the Resend webhook endpoint."""
import json
import uuid

import pytest
from fastapi.testclient import TestClient

from app import app
from services.email import log


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=False)


def test_should_process_delivered_event(client, monkeypatch):
    monkeypatch.delenv("RESEND_WEBHOOK_SECRET", raising=False)
    msg_id = f"re_test_{uuid.uuid4().hex[:8]}"
    log_id = log.insert_log(
        email_type="invoice_sent",
        to_email="x@x.com",
        provider="resend",
    )
    log.mark_sent(log_id, provider_message_id=msg_id)

    event = {
        "type": "email.delivered",
        "data": {"email_id": msg_id},
    }
    resp = client.post("/api/webhooks/resend", json=event)
    assert resp.status_code == 200
    assert resp.json()["affected"] == 1

    from database import db_rows
    rows = db_rows("SELECT status FROM email_log WHERE id = ?", (log_id,))
    assert rows[0]["status"] == "delivered"


def test_should_process_bounced_event(client, monkeypatch):
    monkeypatch.delenv("RESEND_WEBHOOK_SECRET", raising=False)
    msg_id = f"re_test_{uuid.uuid4().hex[:8]}"
    log_id = log.insert_log(
        email_type="welcome",
        to_email="bounce@x.com",
        provider="resend",
    )
    log.mark_sent(log_id, provider_message_id=msg_id)

    event = {
        "type": "email.bounced",
        "data": {"email_id": msg_id},
    }
    resp = client.post("/api/webhooks/resend", json=event)
    assert resp.status_code == 200

    from database import db_rows
    rows = db_rows("SELECT status, bounced_at FROM email_log WHERE id = ?", (log_id,))
    assert rows[0]["status"] == "bounced"
    assert rows[0]["bounced_at"] is not None


def test_should_ignore_unknown_event(client, monkeypatch):
    monkeypatch.delenv("RESEND_WEBHOOK_SECRET", raising=False)
    event = {
        "type": "email.unknown_event",
        "data": {"email_id": "re_test_x"},
    }
    resp = client.post("/api/webhooks/resend", json=event)
    assert resp.status_code == 200
    assert resp.json()["ignored"] is True


def test_should_reject_invalid_signature(client, monkeypatch):
    monkeypatch.setenv("RESEND_WEBHOOK_SECRET", "supersecret")
    resp = client.post(
        "/api/webhooks/resend",
        headers={"svix-signature": "wrong"},
        json={"type": "email.sent", "data": {"email_id": "abc"}},
    )
    assert resp.status_code == 401
