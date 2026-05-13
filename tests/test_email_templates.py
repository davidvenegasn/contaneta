"""Tests for email template rendering service."""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.email_templates import (
    render_email,
    render_invoice_email,
    render_password_reset_email,
    render_payment_email,
    render_quotation_email,
    render_welcome_email,
)


# ---------------------------------------------------------------------------
# Base template structure
# ---------------------------------------------------------------------------


def test_should_include_header_with_branding():
    """Base template must include ContaNeta brand in the header."""
    html = render_email("email/welcome.html", {
        "user_name": "Test",
        "login_url": "https://example.com/login",
    })
    assert "ContaNeta" in html


def test_should_include_footer_with_unsubscribe():
    """Base template must include footer with unsubscribe link placeholder."""
    html = render_email("email/welcome.html", {
        "user_name": "Test",
        "login_url": "https://example.com/login",
    })
    # The unsubscribe link or placeholder must be present
    assert "unsubscribe" in html.lower() or "suscripci" in html.lower()


def test_should_include_copyright_in_footer():
    """Base template footer must include copyright text."""
    html = render_email("email/welcome.html", {
        "user_name": "Test",
        "login_url": "https://example.com/login",
    })
    assert "Todos los derechos reservados" in html


def test_should_include_responsive_meta_tags():
    """Base template must include viewport meta tag for mobile responsiveness."""
    html = render_email("email/welcome.html", {
        "user_name": "Test",
        "login_url": "https://example.com/login",
    })
    assert 'name="viewport"' in html
    assert "width=device-width" in html


def test_should_include_dark_mode_support():
    """Base template must include dark mode media query."""
    html = render_email("email/welcome.html", {
        "user_name": "Test",
        "login_url": "https://example.com/login",
    })
    assert "prefers-color-scheme: dark" in html


def test_should_include_preheader_text():
    """Base template should render preheader text when provided."""
    html = render_email("email/welcome.html", {
        "user_name": "Test",
        "login_url": "https://example.com/login",
        "preheader": "Preview text for email client",
    })
    assert "Preview text for email client" in html


def test_should_use_table_based_layout():
    """Email template must use table-based layout for email client compat."""
    html = render_email("email/welcome.html", {
        "user_name": "Test",
        "login_url": "https://example.com/login",
    })
    assert 'role="presentation"' in html
    assert "<table" in html


# ---------------------------------------------------------------------------
# Welcome email
# ---------------------------------------------------------------------------


def test_should_render_welcome_email_with_user_name():
    """Welcome email must include the user name."""
    html = render_welcome_email(
        user_name="Diego Garcia",
        login_url="https://app.contaneta.com/login",
    )
    assert "Diego Garcia" in html
    assert "https://app.contaneta.com/login" in html
    assert "Bienvenido" in html


def test_should_render_welcome_email_with_branding():
    """Welcome email must include ContaNeta branding."""
    html = render_welcome_email(
        user_name="Maria",
        login_url="https://example.com/login",
    )
    assert "ContaNeta" in html
    assert "#6366f1" in html  # Primary brand color


# ---------------------------------------------------------------------------
# Invoice email
# ---------------------------------------------------------------------------


def test_should_render_invoice_email_with_details():
    """Invoice email must include all invoice details."""
    invoice = {
        "folio": "INV-2026-001",
        "receptor_name": "Acme Corp SA de CV",
        "receptor_rfc": "ACM010101XYZ",
        "date": "2026-05-13",
        "total": "15,000.00",
    }
    html = render_invoice_email(invoice, "https://app.contaneta.com/portal/invoices/1")
    assert "INV-2026-001" in html
    assert "Acme Corp SA de CV" in html
    assert "ACM010101XYZ" in html
    assert "2026-05-13" in html
    assert "15,000.00" in html
    assert "https://app.contaneta.com/portal/invoices/1" in html


def test_should_render_invoice_email_with_partial_data():
    """Invoice email should handle missing optional fields gracefully."""
    invoice = {"folio": "INV-001", "total": "500.00"}
    html = render_invoice_email(invoice, "https://example.com/invoice")
    assert "INV-001" in html
    assert "500.00" in html
    # Should not crash with missing optional fields


# ---------------------------------------------------------------------------
# Quotation email
# ---------------------------------------------------------------------------


def test_should_render_quotation_email_with_details():
    """Quotation email must include all quotation details."""
    quotation = {
        "folio": "COT-2026-042",
        "client_name": "Empresa XYZ",
        "date": "2026-05-13",
        "valid_until": "2026-06-13",
        "total": "25,000.00",
    }
    html = render_quotation_email(quotation, "https://app.contaneta.com/q/abc123")
    assert "COT-2026-042" in html
    assert "Empresa XYZ" in html
    assert "2026-05-13" in html
    assert "2026-06-13" in html
    assert "25,000.00" in html
    assert "https://app.contaneta.com/q/abc123" in html


# ---------------------------------------------------------------------------
# Password reset email
# ---------------------------------------------------------------------------


def test_should_render_password_reset_email_with_url_and_expiry():
    """Password reset email must include reset URL and expiry."""
    html = render_password_reset_email(
        reset_url="https://app.contaneta.com/reset?token=abc123",
        expiry_minutes=30,
    )
    assert "https://app.contaneta.com/reset?token=abc123" in html
    assert "30" in html
    assert "minutos" in html


def test_should_render_password_reset_email_with_security_warning():
    """Password reset email should include security notice."""
    html = render_password_reset_email(
        reset_url="https://example.com/reset?t=x",
        expiry_minutes=60,
    )
    # Should warn about not sharing the link
    assert "seguridad" in html.lower() or "compartas" in html.lower()


# ---------------------------------------------------------------------------
# Payment email
# ---------------------------------------------------------------------------


def test_should_render_payment_email_with_details():
    """Payment email must include all payment details."""
    payment = {
        "amount": "8,500.00",
        "currency": "MXN",
        "date": "2026-05-13",
        "method": "Transferencia bancaria",
        "invoice_folio": "INV-2026-001",
        "payer_name": "Cliente SA de CV",
        "reference": "REF-12345",
    }
    html = render_payment_email(payment)
    assert "8,500.00" in html
    assert "MXN" in html
    assert "2026-05-13" in html
    assert "Transferencia bancaria" in html
    assert "INV-2026-001" in html
    assert "Cliente SA de CV" in html
    assert "REF-12345" in html


# ---------------------------------------------------------------------------
# XSS prevention (context variable escaping)
# ---------------------------------------------------------------------------


def test_should_escape_xss_in_user_name():
    """User-supplied values must be HTML-escaped to prevent XSS."""
    html = render_welcome_email(
        user_name='<script>alert("xss")</script>',
        login_url="https://example.com/login",
    )
    # The raw <script> tag must NOT appear; it should be escaped
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_should_escape_xss_in_invoice_data():
    """Invoice data values must be HTML-escaped to prevent XSS."""
    invoice = {
        "folio": '<img src=x onerror="alert(1)">',
        "receptor_name": "Normal Name",
        "total": "100.00",
    }
    html = render_invoice_email(invoice, "https://example.com")
    assert 'onerror="alert(1)"' not in html
    assert "&lt;img" in html


def test_should_escape_xss_in_quotation_data():
    """Quotation data must be properly escaped."""
    quotation = {
        "folio": "COT-001",
        "client_name": '"><script>alert(1)</script>',
        "total": "100.00",
    }
    html = render_quotation_email(quotation, "https://example.com")
    assert "<script>" not in html


# ---------------------------------------------------------------------------
# Custom unsubscribe URL
# ---------------------------------------------------------------------------


def test_should_include_custom_unsubscribe_url_when_provided():
    """When unsubscribe_url is passed, it should appear in the footer."""
    html = render_email("email/welcome.html", {
        "user_name": "Test",
        "login_url": "https://example.com/login",
        "unsubscribe_url": "https://example.com/unsubscribe?id=123",
    })
    assert "https://example.com/unsubscribe?id=123" in html


# ---------------------------------------------------------------------------
# render_email with current_year
# ---------------------------------------------------------------------------


def test_should_include_current_year_in_footer():
    """Footer should include the current year for copyright."""
    from datetime import datetime, timezone

    html = render_welcome_email("Test", "https://example.com")
    current_year = str(datetime.now(timezone.utc).year)
    assert current_year in html


# ---------------------------------------------------------------------------
# Generic render_email function
# ---------------------------------------------------------------------------


def test_should_render_base_template_directly():
    """render_email should work with the base template directly."""
    html = render_email("email/base_email.html", {})
    assert "<!DOCTYPE html>" in html
    assert "ContaNeta" in html
    assert "utf-8" in html
