"""Tests for email sender and templates."""
import os
from unittest.mock import MagicMock, patch

import pytest

from services import email_sender, email_templates


class TestEmailSenderWithSmtp:
    """Verify SMTP sending when configured."""

    @patch.dict(os.environ, {
        "SMTP_HOST": "smtp.test.com",
        "SMTP_USER": "apikey",
        "SMTP_PASSWORD": "SG.fake_key",
        "SMTP_FROM": "noreply@test.com",
        "SMTP_REPLY_TO": "soporte@test.com",
    })
    @patch("services.email_sender.smtplib.SMTP")
    def test_should_send_multipart_when_html_provided(self, mock_smtp_cls):
        """When both plain and HTML bodies given, send multipart/alternative."""
        # Reload module-level vars
        import importlib
        importlib.reload(email_sender)

        mock_server = MagicMock()
        mock_smtp_cls.return_value.__enter__ = MagicMock(return_value=mock_server)
        mock_smtp_cls.return_value.__exit__ = MagicMock(return_value=False)

        result = email_sender.send_email(
            to="user@example.com",
            subject="Test",
            body_plain="Plain text",
            body_html="<p>HTML</p>",
        )
        assert result is True
        mock_server.starttls.assert_called_once()
        mock_server.login.assert_called_once_with("apikey", "SG.fake_key")
        mock_server.sendmail.assert_called_once()
        # Check the message contains multipart
        sent_msg = mock_server.sendmail.call_args[0][2]
        assert "multipart/alternative" in sent_msg
        # Body parts are base64-encoded by MIMEText; check content types
        assert "text/plain" in sent_msg
        assert "text/html" in sent_msg

        # Restore original module state
        importlib.reload(email_sender)

    @patch.dict(os.environ, {
        "SMTP_HOST": "smtp.test.com",
        "SMTP_USER": "apikey",
        "SMTP_PASSWORD": "SG.fake_key",
    })
    @patch("services.email_sender.smtplib.SMTP")
    def test_should_send_plain_when_no_html(self, mock_smtp_cls):
        """When only plain body, send text/plain."""
        import importlib
        importlib.reload(email_sender)

        mock_server = MagicMock()
        mock_smtp_cls.return_value.__enter__ = MagicMock(return_value=mock_server)
        mock_smtp_cls.return_value.__exit__ = MagicMock(return_value=False)

        result = email_sender.send_email(
            to="user@example.com",
            subject="Test",
            body_plain="Plain only",
        )
        assert result is True
        sent_msg = mock_server.sendmail.call_args[0][2]
        assert "text/plain" in sent_msg

        importlib.reload(email_sender)


class TestEmailSenderSkipsWhenMissing:
    """Verify no SMTP attempt when not configured."""

    def test_should_return_false_in_prod_without_smtp(self):
        """In prod mode without SMTP, send_email returns False."""
        with patch.object(email_sender, "SMTP_HOST", ""), \
             patch.object(email_sender, "SMTP_USER", ""), \
             patch.object(email_sender, "SMTP_PASSWORD", ""), \
             patch.object(email_sender, "DEV_MODE", False):
            result = email_sender.send_email("a@b.com", "Test", "body")
            assert result is False

    def test_should_return_true_in_dev_without_smtp(self):
        """In dev mode without SMTP, send_email logs and returns True."""
        with patch.object(email_sender, "SMTP_HOST", ""), \
             patch.object(email_sender, "SMTP_USER", ""), \
             patch.object(email_sender, "SMTP_PASSWORD", ""), \
             patch.object(email_sender, "DEV_MODE", True):
            result = email_sender.send_email("a@b.com", "Test", "body")
            assert result is True

    def test_should_reject_invalid_email(self):
        """Invalid email addresses should return False immediately."""
        assert email_sender.send_email("", "Test", "body") is False
        assert email_sender.send_email("no-at-sign", "Test", "body") is False


class TestIsConfigured:
    """Verify is_configured() helper."""

    def test_should_return_false_without_env(self):
        with patch.object(email_sender, "SMTP_HOST", ""), \
             patch.object(email_sender, "SMTP_USER", ""), \
             patch.object(email_sender, "SMTP_PASSWORD", ""):
            assert email_sender.is_configured() is False

    def test_should_return_true_with_all_vars(self):
        with patch.object(email_sender, "SMTP_HOST", "smtp.test.com"), \
             patch.object(email_sender, "SMTP_USER", "apikey"), \
             patch.object(email_sender, "SMTP_PASSWORD", "secret"):
            assert email_sender.is_configured() is True


class TestEmailTemplatesRender:
    """Verify all email templates render without error."""

    def test_should_render_welcome_email(self):
        html = email_templates.render_welcome_email("Juan", "https://app.test/portal")
        assert "Juan" in html
        assert "https://app.test/portal" in html
        assert "ContaNeta" in html

    def test_should_render_password_reset_email(self):
        html = email_templates.render_password_reset_email("https://app.test/reset?t=abc", 120)
        assert "https://app.test/reset?t=abc" in html
        assert "120" in html

    def test_should_render_invoice_email(self):
        html = email_templates.render_invoice_email(
            {"folio": "A-001", "receptor_name": "Acme", "date": "2026-01-15", "total": "$1,000"},
            "https://app.test/portal/cfdi/issued/xyz",
        )
        assert "A-001" in html
        assert "Acme" in html

    def test_should_render_quotation_email(self):
        html = email_templates.render_quotation_email(
            {"folio": "Q-100", "client_name": "Client Corp", "total": "$500"},
            "https://app.test/q/abc123",
        )
        assert "Q-100" in html

    def test_should_render_payment_email(self):
        html = email_templates.render_payment_email(
            {"amount": "5000", "currency": "MXN", "method": "Transferencia"},
        )
        assert "5000" in html


class TestHealthSmtpField:
    """Verify /health includes smtp_configured."""

    def test_should_include_smtp_configured_in_health(self):
        from starlette.testclient import TestClient
        from app import app
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get("/health")
        assert r.status_code == 200
        data = r.json()
        assert "smtp_configured" in data
        assert isinstance(data["smtp_configured"], bool)
