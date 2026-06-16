"""Tests for email template rendering (Phase 3)."""

import pytest

from services.email.templates import render

# Template names and their required/typical context variables
TEMPLATES = {
    "welcome": {
        "brand_name": "ContaNeta",
        "user_name": "María López",
        "onboarding_url": "https://app.contaneta.com/portal/onboarding",
    },
    "trial_expiring": {
        "days_until_expiry": 3,
        "trial_expires_at": "2026-06-20",
        "pricing_url": "https://app.contaneta.com/pricing",
    },
    "payment_failed": {
        "brand_name": "ContaNeta",
        "failure_reason": "Tarjeta declinada por fondos insuficientes",
        "amount": 499.00,
        "billing_url": "https://app.contaneta.com/portal/billing",
    },
    "email_verification": {
        "verification_url": "https://app.contaneta.com/verify?token=abc123",
    },
    "password_reset": {
        "reset_url": "https://app.contaneta.com/reset?token=xyz789",
    },
    "invoice_sent": {
        "from_name": "Empresa ABC SA de CV",
        "total": 11600.00,
        "currency": "MXN",
        "serie": "A",
        "folio": "123",
        "fecha_emision": "2026-06-15",
        "uuid": "abc12345-6789-0000-aaaa-bbbbccccdddd",
    },
    "declaration_summary": {
        "periodo": "Mayo 2026",
        "user_name": "Juan Pérez",
        "tipo_declaracion": "Mensual ISR",
        "saldo_a_cargo": 15230.50,
        "saldo_a_favor": 0,
        "linea_captura": "0012345678901234567890",
        "fecha_vencimiento": "2026-06-17",
        "folio_acuse": "AC-2026-05-001",
        "portal_url": "https://app.contaneta.com/portal/declaraciones/1",
        "brand_name": "ContaNeta",
    },
    "csd_expiring": {
        "expires_at": "2026-07-01",
        "days_until_expiry": 15,
        "brand_name": "ContaNeta",
        "settings_url": "https://app.contaneta.com/portal/settings",
    },
    "fiel_expiring": {
        "expires_at": "2026-07-15",
        "days_until_expiry": 29,
        "brand_name": "ContaNeta",
        "settings_url": "https://app.contaneta.com/portal/settings",
    },
    "subscription_renewed": {
        "brand_name": "ContaNeta",
        "plan_name": "Profesional",
        "next_billing_date": "2026-07-15",
    },
}


@pytest.mark.parametrize("template_name", TEMPLATES.keys())
def test_html_renders_without_error(template_name):
    """Each HTML template should render without errors."""
    context = TEMPLATES[template_name]
    html, text = render(template_name, context)
    assert len(html) > 100, f"{template_name}.html rendered too short"
    assert "<html" in html.lower() or "<h2" in html.lower() or "<p" in html.lower()


@pytest.mark.parametrize("template_name", TEMPLATES.keys())
def test_txt_renders_without_error(template_name):
    """Each .txt template should render without errors."""
    context = TEMPLATES[template_name]
    _, text = render(template_name, context)
    assert len(text) > 20, f"{template_name}.txt rendered too short"
    # Text should NOT contain HTML tags
    assert "<html" not in text.lower()
    assert "<div" not in text.lower()


@pytest.mark.parametrize("template_name", TEMPLATES.keys())
def test_txt_contains_key_content(template_name):
    """Plain text version should contain readable content."""
    context = TEMPLATES[template_name]
    _, text = render(template_name, context)
    # Should contain at least one URL or meaningful word
    assert any(word in text.lower() for word in [
        "http", "contaneta", "factura", "suscri", "correo",
        "contraseña", "verifica", "vence", "pago", "declaración",
        "bienvenid", "csd", "fiel", "plan",
    ]), f"{template_name}.txt lacks meaningful content"
