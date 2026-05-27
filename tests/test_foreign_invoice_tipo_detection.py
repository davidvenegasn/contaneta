"""Tests for smart INGRESO/GASTO detection in foreign invoice PDF parser."""
import pytest

from routers.api.invoices._pdf_parse_helpers import _detect_tipo, _parse_invoice_text


class TestDetectTipoFromPdf:
    """Verify _detect_tipo correctly identifies INGRESO vs GASTO vs None."""

    def test_should_detect_ingreso_when_issuer_name_appears_as_seller(self):
        """PDF with user's name at top (seller) and 'Bill to: Acme' → INGRESO."""
        text = (
            "Perla Joselyn Chavez Jaimes\n"
            "89-16 Jamaica Avenue\n"
            "\n"
            "Bill to\n"
            "Intensify Inc\n"
            "billing@example.com\n"
            "\n"
            "Invoice 2026-01-36\n"
            "Total $1012.00"
        )
        result = _parse_invoice_text(
            text, issuer_context={"razon_social": "", "nombre": "Perla Joselyn Chavez Jaimes"}
        )
        assert result["tipo"] == "INGRESO"

    def test_should_detect_gasto_when_user_appears_in_bill_to(self):
        """PDF with 'Bill to: <user>' → GASTO."""
        text = (
            "Stripe Inc\n"
            "500 Howard St\n"
            "\n"
            "Bill to:\n"
            "Perla Joselyn Chavez Jaimes\n"
            "\n"
            "Invoice INV-001\n"
            "Total $29.00"
        )
        result = _parse_invoice_text(
            text, issuer_context={"razon_social": "", "nombre": "Perla Joselyn Chavez Jaimes"}
        )
        assert result["tipo"] == "GASTO"

    def test_should_return_none_when_user_unmatched(self):
        """If user's name doesn't appear in either section, tipo should be None."""
        text = "Random Company LLC\n\nBill to\nAnother Company Inc"
        result = _parse_invoice_text(
            text, issuer_context={"razon_social": "", "nombre": "Perla Joselyn Chavez Jaimes"}
        )
        assert result["tipo"] is None

    def test_should_return_none_without_issuer_context(self):
        """Without issuer context, cannot detect tipo."""
        text = "Perla Joselyn Chavez Jaimes\n\nBill to\nAcme Corp"
        result = _parse_invoice_text(text)
        assert result["tipo"] is None

    def test_should_match_razon_social_over_nombre(self):
        """Prefer razon_social when both are provided."""
        text = (
            "Consultoria ABC SA de CV\n"
            "Av. Reforma 100\n"
            "\n"
            "Bill To\n"
            "Widgets Inc\n"
        )
        result = _parse_invoice_text(
            text,
            issuer_context={"razon_social": "Consultoria ABC SA de CV", "nombre": "Juan Perez"},
        )
        assert result["tipo"] == "INGRESO"

    def test_should_handle_accented_names(self):
        """Accented characters in names should not prevent matching."""
        text = (
            "María García López\n"
            "Calle Luna 42\n"
            "\n"
            "Bill To\n"
            "TechCorp\n"
        )
        result = _parse_invoice_text(
            text, issuer_context={"razon_social": "", "nombre": "Maria Garcia Lopez"}
        )
        assert result["tipo"] == "INGRESO"

    def test_should_return_none_with_empty_issuer_name(self):
        """Empty issuer name should return None, not crash."""
        text = "Some Company\nBill To\nAnother"
        result = _detect_tipo(text, {"razon_social": "", "nombre": ""})
        assert result is None

    def test_should_detect_gasto_for_stripe_receipt(self):
        """Classic Stripe receipt where user is the buyer."""
        text = (
            "Stripe\n"
            "354 Oyster Point Blvd\n"
            "South San Francisco, CA 94080\n"
            "\n"
            "Bill to\n"
            "Freelancer Studio SA de CV\n"
            "RFC: FST210101AB1\n"
            "\n"
            "Invoice INV-2026-001\n"
            "Amount Due $29.00 USD"
        )
        result = _parse_invoice_text(
            text, issuer_context={"razon_social": "Freelancer Studio SA de CV", "nombre": "Ana"}
        )
        assert result["tipo"] == "GASTO"

    def test_should_detect_ingreso_with_invoice_to_variant(self):
        """'Invoice To' is another common variant of 'Bill To'."""
        text = (
            "Mi Empresa Consultores\n"
            "Mexico City\n"
            "\n"
            "Invoice To\n"
            "Big Client LLC\n"
            "New York\n"
        )
        result = _parse_invoice_text(
            text, issuer_context={"razon_social": "Mi Empresa Consultores", "nombre": ""}
        )
        assert result["tipo"] == "INGRESO"
