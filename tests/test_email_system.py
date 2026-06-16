"""Tests for the email scaffolding (no real sending)."""
import uuid

import pytest

from services.email.providers.noop import NoopProvider
from services.email.providers.resend import ResendProvider
from services.email.types import Attachment, EmailMessage
from services.email import config, sender, log, templates


def test_should_default_to_noop_without_key(monkeypatch):
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    monkeypatch.delenv("EMAIL_PROVIDER", raising=False)
    assert config.get_provider_name() == "noop"


def test_should_use_resend_when_key_set(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "re_test_xxx")
    monkeypatch.delenv("EMAIL_PROVIDER", raising=False)
    assert config.get_provider_name() == "resend"


def test_should_respect_explicit_noop_override(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "re_test_xxx")
    monkeypatch.setenv("EMAIL_PROVIDER", "noop")
    assert config.get_provider_name() == "noop"


def test_noop_provider_should_return_success():
    p = NoopProvider()
    result = p.send(EmailMessage(to_email="a@b.com", subject="x", html_body="<p>x</p>"))
    assert result.success
    assert result.provider_message_id.startswith("noop-")


def test_should_render_welcome_template():
    html, text = templates.render("welcome", {"user_name": "David", "brand_name": "ContaNeta"})
    assert "David" in html
    assert "ContaNeta" in html
    assert "David" in text


def test_should_render_invoice_template():
    html, _ = templates.render("invoice_sent", {
        "from_name": "Ana Carolina",
        "total": 5000.0,
        "currency": "MXN",
        "serie": "A",
        "folio": "123",
        "fecha_emision": "2026-06-15",
        "uuid": "abc-123-def",
    })
    assert "Ana Carolina" in html
    assert "5,000.00" in html
    assert "A123" in html


def test_should_render_email_verification_template():
    html, text = templates.render("email_verification", {
        "verification_url": "https://example.com/verify?token=abc123",
    })
    assert "Verifica tu correo" in html
    assert "abc123" in html


def test_should_render_password_reset_template():
    html, text = templates.render("password_reset", {
        "reset_url": "https://example.com/reset?token=xyz",
    })
    assert "Restablecer contraseña" in html
    assert "xyz" in html


def test_should_render_csd_expiring_template():
    html, _ = templates.render("csd_expiring", {
        "expires_at": "2026-07-01",
        "days_until_expiry": 15,
    })
    assert "CSD" in html
    assert "15" in html


def test_should_render_trial_expiring_template():
    html, _ = templates.render("trial_expiring", {
        "days_until_expiry": 3,
        "trial_expires_at": "2026-06-19",
    })
    assert "3 días" in html


def test_should_render_payment_failed_template():
    html, _ = templates.render("payment_failed", {
        "amount": 499.0,
        "failure_reason": "Fondos insuficientes",
    })
    assert "499.00" in html
    assert "Fondos insuficientes" in html


def test_should_send_email_with_noop_and_create_log(monkeypatch):
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    monkeypatch.delenv("EMAIL_PROVIDER", raising=False)
    log_id = sender.send_email(
        to_email="cliente@example.com",
        template="welcome",
        context={"user_name": "Test", "brand_name": "ContaNeta"},
        email_type="welcome",
    )
    assert isinstance(log_id, int)
    from database import db_rows
    rows = db_rows("SELECT status, provider FROM email_log WHERE id = ?", (log_id,))
    assert rows and rows[0]["status"] == "sent"
    assert rows[0]["provider"] == "noop"


def test_should_mark_failed_when_template_missing(monkeypatch):
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    monkeypatch.delenv("EMAIL_PROVIDER", raising=False)
    log_id = sender.send_email(
        to_email="cliente@example.com",
        template="this_template_does_not_exist",
        context={},
    )
    from database import db_rows
    rows = db_rows("SELECT status, error_message FROM email_log WHERE id = ?", (log_id,))
    assert rows[0]["status"] == "failed"
    assert "render error" in (rows[0]["error_message"] or "")


def test_should_update_status_via_webhook():
    msg_id = f"re_msg_{uuid.uuid4().hex[:8]}"
    log_id = log.insert_log(
        email_type="welcome",
        to_email="test@example.com",
        provider="resend",
    )
    log.mark_sent(log_id, provider_message_id=msg_id)
    affected = log.update_status_by_provider_id(msg_id, "delivered", "delivered_at")
    assert affected == 1
    from database import db_rows
    rows = db_rows("SELECT status, delivered_at FROM email_log WHERE id = ?", (log_id,))
    assert rows[0]["status"] == "delivered"
    assert rows[0]["delivered_at"] is not None


def test_should_format_subject_from_context(monkeypatch):
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    monkeypatch.delenv("EMAIL_PROVIDER", raising=False)
    log_id = sender.send_email(
        to_email="test@example.com",
        template="welcome",
        context={"user_name": "Test"},
    )
    from database import db_rows
    rows = db_rows("SELECT subject FROM email_log WHERE id = ?", (log_id,))
    assert rows[0]["subject"] == "Bienvenido a ContaNeta"
