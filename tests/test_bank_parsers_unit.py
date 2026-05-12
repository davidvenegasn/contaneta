"""Comprehensive unit tests for BBVA and Santander bank statement parsers and shared base utilities.

Tests mock pdfplumber so no real PDF files are needed.
"""
from __future__ import annotations

import os
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("APP_DB_PATH", "/tmp/test_bank_parsers_unit.db")
os.environ.setdefault("SESSION_SECRET", "test-secret-bank-parsers-unit")

from services.bank.parsers._base import (  # noqa: E402
    MONTH_ABBR_ES,
    MONTH_FULL_ES,
    extract_full_text,
    extract_text_per_line,
    norm_text,
    parse_amount,
    parse_date_es,
    strip_accents,
)
from services.bank.parsers.bbva import (  # noqa: E402
    _extract_balances,
    _extract_year_from_header,
    _is_likely_deposit,
    _is_noise_line,
    _is_table_header,
    _parse_date as bbva_parse_date,
    parse_bbva,
)
from services.bank.parsers.registry import (  # noqa: E402
    BANK_PARSERS,
    BankParserNotReady,
    list_parsers,
    parse_statement,
    register_parser,
)
from services.bank.parsers.santander import (  # noqa: E402
    _dedupe_shadow_lines,
    _extract_opening_balance,
    _extract_year_and_period,
    _is_deposit as santander_is_deposit,
    _is_noise as santander_is_noise,
    _OCR_MONTH_FIX,
    parse_santander,
)


# ---------------------------------------------------------------------------
# Helpers to build mock pdfplumber objects
# ---------------------------------------------------------------------------

def _make_mock_pdf(pages_text: list[str]):
    """Build a mock pdfplumber PDF context-manager returning controlled text.

    Args:
        pages_text: List of strings, one per page. Each string contains newline-separated lines.

    Returns:
        A MagicMock suitable for patching pdfplumber.open().
    """
    mock_pages = []
    for text in pages_text:
        page = MagicMock()
        page.extract_text.return_value = text
        mock_pages.append(page)

    mock_pdf = MagicMock()
    mock_pdf.pages = mock_pages
    mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
    mock_pdf.__exit__ = MagicMock(return_value=False)
    return mock_pdf


# ===================================================================
# BASE UTILITIES (_base.py)
# ===================================================================

class TestStripAccents:
    """Tests for strip_accents()."""

    def test_should_remove_spanish_accents(self):
        assert strip_accents("Depósito") == "Deposito"
        assert strip_accents("año") == "ano"
        assert strip_accents("México") == "Mexico"
        assert strip_accents("más información") == "mas informacion"

    def test_should_remove_dieresis(self):
        assert strip_accents("güero") == "guero"

    def test_should_remove_tilde(self):
        assert strip_accents("señor") == "senor"
        assert strip_accents("NIÑO") == "NINO"

    def test_should_handle_empty_and_none(self):
        assert strip_accents("") == ""
        assert strip_accents(None) == ""

    def test_should_preserve_ascii(self):
        assert strip_accents("ABC 123") == "ABC 123"
        assert strip_accents("hello world") == "hello world"


class TestNormText:
    """Tests for norm_text()."""

    def test_should_uppercase_and_strip(self):
        assert norm_text("  hello  ") == "HELLO"

    def test_should_collapse_whitespace(self):
        assert norm_text("  Depósito   bancario  ") == "DEPOSITO BANCARIO"

    def test_should_strip_accents_and_uppercase(self):
        assert norm_text("información financiera") == "INFORMACION FINANCIERA"

    def test_should_handle_tabs_and_newlines(self):
        assert norm_text("foo\tbar\nbaz") == "FOO BAR BAZ"

    def test_should_handle_empty_and_none(self):
        assert norm_text("") == ""
        assert norm_text(None) == ""

    def test_should_handle_numeric_input(self):
        assert norm_text(12345) == "12345"


class TestParseAmount:
    """Tests for parse_amount()."""

    def test_should_parse_standard_format(self):
        assert parse_amount("1,234.56") == Decimal("1234.56")

    def test_should_parse_large_number(self):
        assert parse_amount("1,234,567.89") == Decimal("1234567.89")

    def test_should_parse_small_number(self):
        assert parse_amount("0.01") == Decimal("0.01")

    def test_should_parse_zero(self):
        assert parse_amount("0.00") == Decimal("0.00")

    def test_should_parse_negative(self):
        assert parse_amount("-1,234.56") == Decimal("-1234.56")
        assert parse_amount("-500.00") == Decimal("-500.00")

    def test_should_strip_dollar_sign(self):
        assert parse_amount("$1,234.56") == Decimal("1234.56")
        assert parse_amount("$ 1,234.56") == Decimal("1234.56")

    def test_should_parse_no_thousands_separator(self):
        assert parse_amount("500.00") == Decimal("500.00")
        assert parse_amount("99.99") == Decimal("99.99")

    def test_should_return_none_for_empty(self):
        assert parse_amount("") is None
        assert parse_amount(None) is None

    def test_should_return_none_for_no_decimals(self):
        # The regex requires exactly 2 decimal places
        assert parse_amount("123") is None
        assert parse_amount("1,234") is None

    def test_should_return_none_for_text(self):
        assert parse_amount("abc") is None
        assert parse_amount("no amount here") is None

    def test_should_extract_amount_from_surrounding_text(self):
        assert parse_amount("SALDO 1,234.56 MXN") == Decimal("1234.56")


class TestParseDateEs:
    """Tests for parse_date_es()."""

    def test_should_parse_dd_mmm_yy_banorte_style(self):
        assert parse_date_es("01-ENE-26") == date(2026, 1, 1)
        assert parse_date_es("15-DIC-25") == date(2025, 12, 15)
        assert parse_date_es("28-FEB-24") == date(2024, 2, 28)

    def test_should_parse_dd_mmm_yyyy(self):
        assert parse_date_es("01-ENE-2026") == date(2026, 1, 1)
        assert parse_date_es("31-DIC-2025") == date(2025, 12, 31)

    def test_should_parse_dd_slash_mmm_yy(self):
        assert parse_date_es("01/ENE/26") == date(2026, 1, 1)

    def test_should_parse_dd_mm_yyyy_slash(self):
        assert parse_date_es("01/01/2026") == date(2026, 1, 1)
        assert parse_date_es("15/12/2025") == date(2025, 12, 15)

    def test_should_parse_dd_mm_yy_slash(self):
        assert parse_date_es("15/12/25") == date(2025, 12, 15)
        assert parse_date_es("01/01/26") == date(2026, 1, 1)

    def test_should_parse_dd_mm_yyyy_dash(self):
        assert parse_date_es("01-01-2026") == date(2026, 1, 1)

    def test_should_parse_full_month_spanish(self):
        assert parse_date_es("01 de enero 2026") == date(2026, 1, 1)
        assert parse_date_es("15 de diciembre de 2025") == date(2025, 12, 15)

    def test_should_parse_full_month_accented(self):
        # strip_accents is called, so accented month names should work
        assert parse_date_es("01 de febrero 2024") == date(2024, 2, 1)

    def test_should_parse_iso_format(self):
        assert parse_date_es("2026-01-15") == date(2026, 1, 15)
        assert parse_date_es("2025-12-31") == date(2025, 12, 31)

    def test_should_parse_all_month_abbreviations(self):
        for abbr, month_num in MONTH_ABBR_ES.items():
            if abbr == "SET":
                continue  # alias for SEP
            result = parse_date_es(f"15-{abbr}-24")
            assert result is not None, f"Failed for {abbr}"
            assert result.month == month_num, f"{abbr}: expected month {month_num}, got {result.month}"

    def test_should_parse_set_as_september(self):
        assert parse_date_es("15-SET-24") == date(2024, 9, 15)

    def test_should_return_none_for_empty(self):
        assert parse_date_es("") is None
        assert parse_date_es(None) is None

    def test_should_return_none_for_invalid_text(self):
        assert parse_date_es("not a date") is None
        assert parse_date_es("hello world") is None

    def test_should_return_none_for_invalid_day_month(self):
        assert parse_date_es("32/13/2026") is None

    def test_should_handle_leading_trailing_whitespace(self):
        assert parse_date_es("  01-ENE-26  ") == date(2026, 1, 1)

    def test_should_handle_case_insensitivity(self):
        assert parse_date_es("01-ene-26") == date(2026, 1, 1)
        assert parse_date_es("15-Dic-2025") == date(2025, 12, 15)


class TestExtractTextPerLine:
    """Tests for extract_text_per_line()."""

    @patch("pdfplumber.open")
    def test_should_return_tuples_of_page_line_text(self, mock_open):
        mock_pdf = _make_mock_pdf(["Line one\nLine two\nLine three"])
        mock_open.return_value = mock_pdf

        result = extract_text_per_line("/fake/path.pdf")

        assert len(result) == 3
        assert result[0] == (1, 1, "Line one")
        assert result[1] == (1, 2, "Line two")
        assert result[2] == (1, 3, "Line three")

    @patch("pdfplumber.open")
    def test_should_handle_multiple_pages(self, mock_open):
        mock_pdf = _make_mock_pdf(["Page1 Line1\nPage1 Line2", "Page2 Line1"])
        mock_open.return_value = mock_pdf

        result = extract_text_per_line("/fake/path.pdf")

        assert len(result) == 3
        assert result[0] == (1, 1, "Page1 Line1")
        assert result[1] == (1, 2, "Page1 Line2")
        assert result[2] == (2, 1, "Page2 Line1")

    @patch("pdfplumber.open")
    def test_should_handle_empty_page(self, mock_open):
        mock_pdf = _make_mock_pdf(["Line one", None])
        mock_pdf.pages[1].extract_text.return_value = None
        mock_open.return_value = mock_pdf

        result = extract_text_per_line("/fake/path.pdf")
        # Page 1 has "Line one"; page 2 returns None -> "" -> splits into [""] -> (2, 1, "")
        assert len(result) == 2
        assert result[0] == (1, 1, "Line one")
        assert result[1] == (2, 1, "")

    @patch("pdfplumber.open")
    def test_should_return_empty_on_exception(self, mock_open):
        mock_open.side_effect = Exception("PDF corrupt")

        result = extract_text_per_line("/fake/path.pdf")
        assert result == []


class TestExtractFullText:
    """Tests for extract_full_text()."""

    @patch("pdfplumber.open")
    def test_should_return_concatenated_pages(self, mock_open):
        mock_pdf = _make_mock_pdf(["Page 1 content", "Page 2 content"])
        mock_open.return_value = mock_pdf

        result = extract_full_text("/fake/path.pdf")
        assert "Page 1 content" in result
        assert "Page 2 content" in result

    @patch("pdfplumber.open")
    def test_should_return_empty_on_exception(self, mock_open):
        mock_open.side_effect = Exception("PDF error")

        result = extract_full_text("/fake/path.pdf")
        assert result == ""


class TestMonthMappings:
    """Verify completeness of month abbreviation and full-name maps."""

    def test_month_abbr_has_12_months(self):
        # SET is an alias for SEP, so 13 entries total
        values = set(MONTH_ABBR_ES.values())
        assert values == set(range(1, 13))

    def test_month_full_has_12_months(self):
        values = set(MONTH_FULL_ES.values())
        assert values == set(range(1, 13))

    def test_month_abbr_keys_are_uppercase(self):
        for key in MONTH_ABBR_ES:
            assert key == key.upper()

    def test_month_full_keys_are_uppercase(self):
        for key in MONTH_FULL_ES:
            assert key == key.upper()


# ===================================================================
# REGISTRY (registry.py)
# ===================================================================

class TestRegistry:
    """Tests for the parser registry."""

    def test_should_list_all_expected_parsers(self):
        info = list_parsers()
        for bank in ("BBVA", "SANTANDER"):
            assert bank in info, f"{bank} not in registry"

    def test_should_include_parser_metadata(self):
        info = list_parsers()
        for bank, data in info.items():
            assert "experimental" in data
            assert "parser" in data
            assert isinstance(data["experimental"], bool)
            assert isinstance(data["parser"], str)

    def test_should_raise_keyerror_for_unknown_bank(self):
        with pytest.raises(KeyError, match="No parser registered"):
            parse_statement("NONEXISTENT_BANK_XYZ", "/fake/path.pdf")

    def test_should_block_experimental_in_prod(self, monkeypatch):
        monkeypatch.setenv("ENV", "prod")
        monkeypatch.setenv("DEV_MODE", "0")
        with pytest.raises(BankParserNotReady):
            parse_statement("BBVA", "/fake/path.pdf")

    def test_should_allow_experimental_in_dev(self, monkeypatch):
        monkeypatch.setenv("ENV", "dev")
        monkeypatch.setenv("DEV_MODE", "1")
        # Should not raise BankParserNotReady — parser runs (returns [] for missing file)
        result = parse_statement("BBVA", "/fake/nonexistent.pdf")
        assert isinstance(result, list)

    def test_should_allow_experimental_in_prod_with_dev_mode(self, monkeypatch):
        monkeypatch.setenv("ENV", "prod")
        monkeypatch.setenv("DEV_MODE", "1")
        # DEV_MODE=1 overrides prod check
        result = parse_statement("BBVA", "/fake/nonexistent.pdf")
        assert isinstance(result, list)

    def test_register_parser_uppercases_name(self):
        dummy = lambda path: []
        register_parser("test_bank_xyz", dummy, experimental=False)
        assert "TEST_BANK_XYZ" in BANK_PARSERS
        fn, is_exp = BANK_PARSERS["TEST_BANK_XYZ"]
        assert fn is dummy
        assert is_exp is False
        # Clean up
        del BANK_PARSERS["TEST_BANK_XYZ"]


# ===================================================================
# BBVA PARSER (bbva.py)
# ===================================================================

class TestBbvaHelpers:
    """Tests for BBVA parser internal helpers."""

    def test_extract_year_from_periodo_header(self):
        lines = [
            (1, 1, "BBVA MEXICO"),
            (1, 2, "Periodo DEL 01/04/2025 AL 30/04/2025"),
        ]
        assert _extract_year_from_header(lines) == 2025

    def test_extract_year_from_fecha_corte(self):
        lines = [
            (1, 1, "BBVA MEXICO"),
            (1, 2, "Fecha de Corte 30/04/2025"),
        ]
        assert _extract_year_from_header(lines) == 2025

    def test_extract_year_returns_none_when_not_found(self):
        lines = [
            (1, 1, "BBVA MEXICO"),
            (1, 2, "Some other text"),
        ]
        assert _extract_year_from_header(lines) is None

    def test_extract_balances_opening(self):
        lines = [
            (1, 1, "Saldo de Operación Inicial 10,000.00"),
        ]
        opening, closing = _extract_balances(lines)
        assert opening == Decimal("10000.00")
        assert closing is None

    def test_extract_balances_closing(self):
        lines = [
            (1, 1, "SALDO FINAL 15,000.00"),
        ]
        opening, closing = _extract_balances(lines)
        assert opening is None
        assert closing == Decimal("15000.00")

    def test_extract_balances_both(self):
        lines = [
            (1, 1, "Saldo de Liquidacion Inicial 10,000.00"),
            (1, 2, "SALDO FINAL 15,000.00"),
        ]
        opening, closing = _extract_balances(lines)
        assert opening == Decimal("10000.00")
        assert closing == Decimal("15000.00")

    def test_is_table_header_positive(self):
        assert _is_table_header("FECHA OPER FECHA LIQ COD DESCRIPCION CARGOS ABONOS SALDO")
        assert _is_table_header("FECHA   CARGOS  ABONOS")

    def test_is_table_header_negative(self):
        assert not _is_table_header("01/ENE 01/ENE C19 SPEI RECIBIDO")
        assert not _is_table_header("Normal transaction line")

    def test_is_noise_line_positive(self):
        assert _is_noise_line("ESTADO DE CUENTA No. 123456")
        assert _is_noise_line("PAGINA 1 DE 3")
        assert _is_noise_line("BBVA MEXICO SA")
        assert _is_noise_line("1/7")
        assert _is_noise_line("3 / 5")
        assert _is_noise_line("")

    def test_is_noise_line_negative(self):
        assert not _is_noise_line("01/ENE 01/ENE C19 SPEI RECIBIDO 5,000.00 15,000.00")
        assert not _is_noise_line("Pago de nómina")

    def test_bbva_parse_date_valid(self):
        assert bbva_parse_date(1, "ENE", 2026) == date(2026, 1, 1)
        assert bbva_parse_date(15, "DIC", 2025) == date(2025, 12, 15)
        assert bbva_parse_date(28, "FEB", 2024) == date(2024, 2, 28)

    def test_bbva_parse_date_invalid_month(self):
        assert bbva_parse_date(1, "XYZ", 2026) is None

    def test_bbva_parse_date_invalid_day(self):
        assert bbva_parse_date(31, "FEB", 2025) is None

    def test_is_likely_deposit_positive(self):
        assert _is_likely_deposit("DEPOSITO EN EFECTIVO", "")
        assert _is_likely_deposit("SPEI RECIBIDO DE JUAN", "")
        assert _is_likely_deposit("TRANSFERENCIA RECIBIDA", "")
        assert _is_likely_deposit("NOMINA QUINCENAL", "")
        assert _is_likely_deposit("DEVOLUCION IVA", "")
        assert _is_likely_deposit("BONIFICACION POR PROMOCION", "")
        assert _is_likely_deposit("INTERESES GANADOS", "")
        assert _is_likely_deposit("ABONO TRANSFERENCIA", "")

    def test_is_likely_deposit_negative(self):
        assert not _is_likely_deposit("PAGO TARJETA CREDITO", "")
        assert not _is_likely_deposit("COMPRA EN TIENDA", "")
        assert not _is_likely_deposit("RETIRO CAJERO", "")
        assert not _is_likely_deposit("COMISION POR SERVICIO", "")


class TestBbvaParser:
    """Tests for parse_bbva() with mock PDF text."""

    def _build_bbva_pdf_text(self, movements_text: str, year: str = "2025") -> str:
        """Build a realistic BBVA PDF page text with header and movement section."""
        return (
            f"BBVA MEXICO SA\n"
            f"Periodo DEL 01/04/{year} AL 30/04/{year}\n"
            f"Saldo de Operación Inicial 10,000.00\n"
            f"DETALLE DE MOVIMIENTOS\n"
            f"FECHA OPER FECHA LIQ COD DESCRIPCION CARGOS ABONOS SALDO\n"
            f"{movements_text}\n"
            f"TOTAL DE MOVIMIENTOS 3"
        )

    @patch("pdfplumber.open")
    def test_should_parse_single_deposit(self, mock_open):
        text = self._build_bbva_pdf_text(
            "01/ABR 01/ABR C19 SPEI RECIBIDO DE EMPRESA SA 5,000.00 15,000.00"
        )
        mock_pdf = _make_mock_pdf([text])
        mock_open.return_value = mock_pdf

        movements = parse_bbva("/fake/bbva.pdf")

        assert len(movements) == 1
        m = movements[0]
        assert m["fecha"] == "2025-04-01"
        assert m["deposito"] == Decimal("5000.00")
        assert m["retiro"] is None
        assert m["saldo"] == Decimal("15000.00")
        assert "SPEI RECIBIDO" in m["descripcion"]

    @patch("pdfplumber.open")
    def test_should_parse_single_withdrawal(self, mock_open):
        text = self._build_bbva_pdf_text(
            "05/ABR 05/ABR S39 PAGO TARJETA CREDITO 3,000.00 12,000.00"
        )
        mock_pdf = _make_mock_pdf([text])
        mock_open.return_value = mock_pdf

        movements = parse_bbva("/fake/bbva.pdf")

        assert len(movements) == 1
        m = movements[0]
        assert m["fecha"] == "2025-04-05"
        assert m["retiro"] == Decimal("3000.00")
        assert m["deposito"] is None
        assert m["saldo"] == Decimal("12000.00")

    @patch("pdfplumber.open")
    def test_should_parse_multiple_movements(self, mock_open):
        text = self._build_bbva_pdf_text(
            "01/ABR 01/ABR C19 SPEI RECIBIDO EMPRESA SA 5,000.00 15,000.00\n"
            "05/ABR 05/ABR S39 PAGO SERVICIO LUZ 1,200.00 13,800.00\n"
            "10/ABR 10/ABR C19 DEPOSITO EN EFECTIVO 2,000.00 15,800.00"
        )
        mock_pdf = _make_mock_pdf([text])
        mock_open.return_value = mock_pdf

        movements = parse_bbva("/fake/bbva.pdf")

        assert len(movements) == 3
        assert movements[0]["fecha"] == "2025-04-01"
        assert movements[1]["fecha"] == "2025-04-05"
        assert movements[2]["fecha"] == "2025-04-10"

    @patch("pdfplumber.open")
    def test_should_handle_continuation_lines(self, mock_open):
        text = self._build_bbva_pdf_text(
            "01/ABR 01/ABR C19 SPEI RECIBIDO 5,000.00 15,000.00\n"
            "EMPRESA SA DE CV\n"
            "RFC: ABC123456789"
        )
        mock_pdf = _make_mock_pdf([text])
        mock_open.return_value = mock_pdf

        movements = parse_bbva("/fake/bbva.pdf")

        assert len(movements) == 1
        m = movements[0]
        assert "EMPRESA SA DE CV" in m["descripcion"]
        assert "RFC: ABC123456789" in m["descripcion"]

    @patch("pdfplumber.open")
    def test_should_handle_reference_line(self, mock_open):
        text = self._build_bbva_pdf_text(
            "01/ABR 01/ABR C19 SPEI RECIBIDO 5,000.00 15,000.00\n"
            "Ref. 1234567890"
        )
        mock_pdf = _make_mock_pdf([text])
        mock_open.return_value = mock_pdf

        movements = parse_bbva("/fake/bbva.pdf")

        assert len(movements) == 1
        assert movements[0]["referencia"] == "1234567890"

    @patch("pdfplumber.open")
    def test_should_extract_year_from_header(self, mock_open):
        text = (
            "BBVA MEXICO SA\n"
            "Periodo DEL 01/01/2023 AL 31/01/2023\n"
            "DETALLE DE MOVIMIENTOS\n"
            "FECHA OPER FECHA LIQ COD DESCRIPCION CARGOS ABONOS SALDO\n"
            "15/ENE 15/ENE C19 DEPOSITO 1,000.00 11,000.00\n"
            "TOTAL DE MOVIMIENTOS 1"
        )
        mock_pdf = _make_mock_pdf([text])
        mock_open.return_value = mock_pdf

        movements = parse_bbva("/fake/bbva.pdf")

        assert len(movements) == 1
        assert movements[0]["fecha"] == "2023-01-15"

    @patch("pdfplumber.open")
    def test_should_return_empty_for_empty_pdf(self, mock_open):
        mock_pdf = _make_mock_pdf([""])
        mock_pdf.pages[0].extract_text.return_value = None
        mock_open.return_value = mock_pdf

        movements = parse_bbva("/fake/bbva.pdf")
        assert movements == []

    @patch("pdfplumber.open")
    def test_should_return_empty_for_no_movement_section(self, mock_open):
        text = "BBVA MEXICO SA\nSome random header text\nNo movement section here"
        mock_pdf = _make_mock_pdf([text])
        mock_open.return_value = mock_pdf

        movements = parse_bbva("/fake/bbva.pdf")
        assert movements == []

    @patch("pdfplumber.open")
    def test_should_skip_noise_lines_inside_movements(self, mock_open):
        text = self._build_bbva_pdf_text(
            "01/ABR 01/ABR C19 SPEI RECIBIDO 5,000.00 15,000.00\n"
            "PAGINA 2 DE 3\n"
            "05/ABR 05/ABR S39 PAGO SERVICIO 1,000.00 14,000.00"
        )
        mock_pdf = _make_mock_pdf([text])
        mock_open.return_value = mock_pdf

        movements = parse_bbva("/fake/bbva.pdf")
        assert len(movements) == 2

    @patch("pdfplumber.open")
    def test_should_default_year_to_2025_when_no_header(self, mock_open):
        text = (
            "DETALLE DE MOVIMIENTOS\n"
            "FECHA OPER FECHA LIQ COD DESCRIPCION CARGOS ABONOS SALDO\n"
            "15/ENE 15/ENE C19 DEPOSITO 1,000.00 11,000.00\n"
            "TOTAL DE MOVIMIENTOS 1"
        )
        mock_pdf = _make_mock_pdf([text])
        mock_open.return_value = mock_pdf

        movements = parse_bbva("/fake/bbva.pdf")
        assert len(movements) == 1
        assert movements[0]["fecha"] == "2025-01-15"

    @patch("pdfplumber.open")
    def test_should_extract_code_from_movement(self, mock_open):
        text = self._build_bbva_pdf_text(
            "01/ABR 01/ABR C19 SPEI RECIBIDO 5,000.00 15,000.00"
        )
        mock_pdf = _make_mock_pdf([text])
        mock_open.return_value = mock_pdf

        movements = parse_bbva("/fake/bbva.pdf")
        assert movements[0]["code"] == "C19"

    @patch("pdfplumber.open")
    def test_should_handle_movement_with_three_amounts(self, mock_open):
        # Simulating: amount, saldo_oper, saldo_liq
        text = self._build_bbva_pdf_text(
            "01/ABR 01/ABR C19 DEPOSITO EN EFECTIVO 5,000.00 15,000.00 15,000.00"
        )
        mock_pdf = _make_mock_pdf([text])
        mock_open.return_value = mock_pdf

        movements = parse_bbva("/fake/bbva.pdf")
        assert len(movements) == 1
        m = movements[0]
        assert m["deposito"] == Decimal("5000.00")
        assert m["saldo"] == Decimal("15000.00")

    @patch("pdfplumber.open")
    def test_should_handle_movement_with_one_amount(self, mock_open):
        text = self._build_bbva_pdf_text(
            "01/ABR 01/ABR C19 SPEI RECIBIDO 5,000.00"
        )
        mock_pdf = _make_mock_pdf([text])
        mock_open.return_value = mock_pdf

        movements = parse_bbva("/fake/bbva.pdf")
        assert len(movements) == 1
        m = movements[0]
        assert m["deposito"] == Decimal("5000.00")
        assert m["saldo"] is None

    @patch("pdfplumber.open")
    def test_should_handle_multi_page_pdf(self, mock_open):
        page1 = (
            "BBVA MEXICO SA\n"
            "Periodo DEL 01/04/2025 AL 30/04/2025\n"
            "DETALLE DE MOVIMIENTOS\n"
            "FECHA OPER FECHA LIQ COD DESCRIPCION CARGOS ABONOS SALDO\n"
            "01/ABR 01/ABR C19 SPEI RECIBIDO 5,000.00 15,000.00"
        )
        page2 = (
            "05/ABR 05/ABR S39 PAGO SERVICIO 1,000.00 14,000.00\n"
            "TOTAL DE MOVIMIENTOS 2"
        )
        mock_pdf = _make_mock_pdf([page1, page2])
        mock_open.return_value = mock_pdf

        movements = parse_bbva("/fake/bbva.pdf")
        assert len(movements) == 2

    @patch("pdfplumber.open")
    def test_should_include_raw_line(self, mock_open):
        text = self._build_bbva_pdf_text(
            "01/ABR 01/ABR C19 SPEI RECIBIDO 5,000.00 15,000.00"
        )
        mock_pdf = _make_mock_pdf([text])
        mock_open.return_value = mock_pdf

        movements = parse_bbva("/fake/bbva.pdf")
        assert "raw_line" in movements[0]
        assert "01/ABR" in movements[0]["raw_line"]

    @patch("pdfplumber.open")
    def test_should_have_standard_keys(self, mock_open):
        text = self._build_bbva_pdf_text(
            "01/ABR 01/ABR C19 SPEI RECIBIDO 5,000.00 15,000.00"
        )
        mock_pdf = _make_mock_pdf([text])
        mock_open.return_value = mock_pdf

        movements = parse_bbva("/fake/bbva.pdf")
        required_keys = {"fecha", "descripcion", "deposito", "retiro", "saldo", "referencia"}
        assert required_keys.issubset(movements[0].keys())


# ===================================================================
# SANTANDER PARSER (santander.py)
# ===================================================================

class TestSantanderHelpers:
    """Tests for Santander parser internal helpers."""

    def test_dedupe_shadow_lines_removes_doubled(self):
        lines = [
            (1, 1, "03-MAR-2025 Normal line"),
            (1, 2, "0033--MMAARR--22002255 Shadow line"),
            (1, 3, "Another normal line"),
        ]
        result = _dedupe_shadow_lines(lines)
        assert len(result) == 2
        assert result[0][2] == "03-MAR-2025 Normal line"
        assert result[1][2] == "Another normal line"

    def test_dedupe_shadow_lines_preserves_short_lines(self):
        lines = [
            (1, 1, "Short"),
            (1, 2, "Also OK"),
        ]
        result = _dedupe_shadow_lines(lines)
        assert len(result) == 2

    def test_dedupe_shadow_lines_empty_input(self):
        assert _dedupe_shadow_lines([]) == []

    def test_dedupe_shadow_lines_all_normal(self):
        lines = [
            (1, 1, "This is a normal line of text"),
            (1, 2, "And another perfectly normal line"),
        ]
        result = _dedupe_shadow_lines(lines)
        assert len(result) == 2

    def test_extract_year_and_period_from_periodo(self):
        lines = [
            (1, 1, "BANCO SANTANDER"),
            (1, 2, "PERIODO DEL 01-MAR-2025 AL 31-MAR-2025"),
        ]
        assert _extract_year_and_period(lines) == 2025

    def test_extract_year_and_period_from_corte(self):
        lines = [
            (1, 1, "CORTE AL 31-MAR-2025"),
        ]
        assert _extract_year_and_period(lines) == 2025

    def test_extract_year_and_period_returns_none_when_not_found(self):
        lines = [
            (1, 1, "BANCO SANTANDER"),
            (1, 2, "Some other header text"),
        ]
        assert _extract_year_and_period(lines) is None

    def test_extract_opening_balance(self):
        lines = [
            (1, 1, "SALDO FINAL DEL PERIODO ANTERIOR: $10,000.00"),
        ]
        assert _extract_opening_balance(lines) == Decimal("10000.00")

    def test_extract_opening_balance_saldo_inicial(self):
        lines = [
            (1, 1, "SALDO INICIAL: $5,000.00"),
        ]
        assert _extract_opening_balance(lines) == Decimal("5000.00")

    def test_extract_opening_balance_returns_none(self):
        lines = [
            (1, 1, "Some random text"),
        ]
        assert _extract_opening_balance(lines) is None

    def test_ocr_month_fix_mappings(self):
        assert _OCR_MONTH_FIX["AG0"] == "AGO"
        assert _OCR_MONTH_FIX["AGD"] == "AGO"
        assert _OCR_MONTH_FIX["0CT"] == "OCT"
        assert _OCR_MONTH_FIX["N0V"] == "NOV"
        assert _OCR_MONTH_FIX["D1C"] == "DIC"
        assert _OCR_MONTH_FIX["FE8"] == "FEB"
        assert _OCR_MONTH_FIX["MA8"] == "MAR"

    def test_santander_is_deposit_positive(self):
        assert santander_is_deposit("DEPOSITO EN EFECTIVO")
        assert santander_is_deposit("SPEI RECIBIDO DE EMPRESA")
        assert santander_is_deposit("TRANSFERENCIA RECIBIDA")
        assert santander_is_deposit("INTERESES GANADOS")
        assert santander_is_deposit("DEVOLUCION IVA")
        assert santander_is_deposit("BONIFICACION")
        assert santander_is_deposit("ABONO POR TRANSFERENCIA")

    def test_santander_is_deposit_negative(self):
        assert not santander_is_deposit("PAGO TARJETA DE CREDITO")
        assert not santander_is_deposit("RETIRO CAJERO")
        assert not santander_is_deposit("COMISION POR SERVICIO")

    def test_santander_is_noise_positive(self):
        assert santander_is_noise("BANCO SANTANDER MEXICO")
        assert santander_is_noise("INSTITUCION DE BANCA MULTIPLE")
        assert santander_is_noise("GAT NOMINAL 5%")
        assert santander_is_noise("SALDO PROMEDIO 15,000.00")
        assert santander_is_noise("INFORMACION FISCAL EJERCICIO 2025")
        assert santander_is_noise("CADENA ORIGINAL DEL TIMBRE DIGITAL")

    def test_santander_is_noise_negative(self):
        assert not santander_is_noise("09-MAR-2025 1234 SPEI RECIBIDO 5,000.00")
        assert not santander_is_noise("PAGO DE NOMINA QUINCENAL")


class TestSantanderParser:
    """Tests for parse_santander() with mock PDF text."""

    def _build_santander_pdf_text(
        self, movements_text: str, year: str = "2025", month: str = "MAR"
    ) -> str:
        """Build a realistic Santander PDF page text."""
        return (
            f"BANCO SANTANDER MEXICO\n"
            f"PERIODO DEL 01-{month}-{year} AL 31-{month}-{year}\n"
            f"SALDO FINAL DEL PERIODO ANTERIOR: $10,000.00\n"
            f"DETALLE DE MOVIMIENTOS\n"
            f"FECHA FOLIO DESCRIPCION DEPOSITO RETIRO SALDO\n"
            f"{movements_text}\n"
            f"TOTAL DE MOVIMIENTOS 3"
        )

    @patch("pdfplumber.open")
    def test_should_parse_single_deposit(self, mock_open):
        text = self._build_santander_pdf_text(
            "09-MAR-2025 1234 SPEI RECIBIDO EMPRESA SA 5,000.00 15,000.00"
        )
        mock_pdf = _make_mock_pdf([text])
        mock_open.return_value = mock_pdf

        movements = parse_santander("/fake/santander.pdf")

        assert len(movements) == 1
        m = movements[0]
        assert m["fecha"] == "2025-03-09"
        assert m["deposito"] == Decimal("5000.00")
        assert m["retiro"] is None
        assert m["saldo"] == Decimal("15000.00")
        assert "SPEI RECIBIDO" in m["descripcion"]

    @patch("pdfplumber.open")
    def test_should_parse_single_withdrawal(self, mock_open):
        text = self._build_santander_pdf_text(
            "15-MAR-2025 5678 PAGO TARJETA CREDITO 3,000.00 12,000.00"
        )
        mock_pdf = _make_mock_pdf([text])
        mock_open.return_value = mock_pdf

        movements = parse_santander("/fake/santander.pdf")

        assert len(movements) == 1
        m = movements[0]
        assert m["fecha"] == "2025-03-15"
        assert m["retiro"] == Decimal("3000.00")
        assert m["deposito"] is None

    @patch("pdfplumber.open")
    def test_should_parse_multiple_movements(self, mock_open):
        text = self._build_santander_pdf_text(
            "01-MAR-2025 1001 SPEI RECIBIDO EMPRESA 5,000.00 15,000.00\n"
            "10-MAR-2025 1002 PAGO SERVICIO CFE 1,200.00 13,800.00\n"
            "20-MAR-2025 1003 DEPOSITO EN EFECTIVO 2,000.00 15,800.00"
        )
        mock_pdf = _make_mock_pdf([text])
        mock_open.return_value = mock_pdf

        movements = parse_santander("/fake/santander.pdf")

        assert len(movements) == 3
        assert movements[0]["fecha"] == "2025-03-01"
        assert movements[1]["fecha"] == "2025-03-10"
        assert movements[2]["fecha"] == "2025-03-20"

    @patch("pdfplumber.open")
    def test_should_handle_continuation_lines(self, mock_open):
        text = self._build_santander_pdf_text(
            "09-MAR-2025 1234 SPEI RECIBIDO 5,000.00 15,000.00\n"
            "EMPRESA SA DE CV RFC ABC123456789\n"
            "CONCEPTO PAGO FACTURA 001"
        )
        mock_pdf = _make_mock_pdf([text])
        mock_open.return_value = mock_pdf

        movements = parse_santander("/fake/santander.pdf")

        assert len(movements) == 1
        m = movements[0]
        assert "EMPRESA SA DE CV" in m["descripcion"]
        assert "CONCEPTO PAGO FACTURA" in m["descripcion"]

    @patch("pdfplumber.open")
    def test_should_extract_folio(self, mock_open):
        text = self._build_santander_pdf_text(
            "09-MAR-2025 98765 SPEI RECIBIDO 5,000.00 15,000.00"
        )
        mock_pdf = _make_mock_pdf([text])
        mock_open.return_value = mock_pdf

        movements = parse_santander("/fake/santander.pdf")
        assert movements[0]["referencia"] == "98765"

    @patch("pdfplumber.open")
    def test_should_extract_reference_from_continuation(self, mock_open):
        text = self._build_santander_pdf_text(
            "09-MAR-2025 SPEI RECIBIDO 5,000.00 15,000.00\n"
            "REF 1234567890ABCDEF"
        )
        mock_pdf = _make_mock_pdf([text])
        mock_open.return_value = mock_pdf

        movements = parse_santander("/fake/santander.pdf")
        assert len(movements) == 1
        assert movements[0]["referencia"] == "1234567890ABCDEF"

    @patch("pdfplumber.open")
    def test_should_return_empty_for_empty_pdf(self, mock_open):
        mock_pdf = _make_mock_pdf([""])
        mock_pdf.pages[0].extract_text.return_value = None
        mock_open.return_value = mock_pdf

        movements = parse_santander("/fake/santander.pdf")
        assert movements == []

    @patch("pdfplumber.open")
    def test_should_return_empty_for_no_movement_section(self, mock_open):
        text = "BANCO SANTANDER MEXICO\nSome random header\nNo movements here"
        mock_pdf = _make_mock_pdf([text])
        mock_open.return_value = mock_pdf

        movements = parse_santander("/fake/santander.pdf")
        assert movements == []

    @patch("pdfplumber.open")
    def test_should_handle_ocr_month_artifacts(self, mock_open):
        # AG0 should be corrected to AGO (August)
        text = (
            "BANCO SANTANDER MEXICO\n"
            "PERIODO DEL 01-AGO-2025 AL 31-AGO-2025\n"
            "SALDO FINAL DEL PERIODO ANTERIOR: $10,000.00\n"
            "DETALLE DE MOVIMIENTOS\n"
            "FECHA FOLIO DESCRIPCION DEPOSITO RETIRO SALDO\n"
            "15-AG0-2025 1234 DEPOSITO EN EFECTIVO 5,000.00 15,000.00\n"
            "TOTAL DE MOVIMIENTOS 1"
        )
        mock_pdf = _make_mock_pdf([text])
        mock_open.return_value = mock_pdf

        movements = parse_santander("/fake/santander.pdf")
        assert len(movements) == 1
        assert movements[0]["fecha"] == "2025-08-15"

    @patch("pdfplumber.open")
    def test_should_handle_shadow_lines(self, mock_open):
        text = (
            "BANCO SANTANDER MEXICO\n"
            "PERIODO DEL 01-MAR-2025 AL 31-MAR-2025\n"
            "SALDO FINAL DEL PERIODO ANTERIOR: $10,000.00\n"
            "DETALLE DE MOVIMIENTOS\n"
            "FECHA FOLIO DESCRIPCION DEPOSITO RETIRO SALDO\n"
            "09-MAR-2025 1234 DEPOSITO EN EFECTIVO 5,000.00 15,000.00\n"
            "0099--MMAARR--22002255  11223344  DDEEPPOOSSIITTOO  EENN  EEFFEECCTTIIVVOO\n"
            "15-MAR-2025 5678 PAGO SERVICIO 1,000.00 14,000.00\n"
            "TOTAL DE MOVIMIENTOS 2"
        )
        mock_pdf = _make_mock_pdf([text])
        mock_open.return_value = mock_pdf

        movements = parse_santander("/fake/santander.pdf")
        # Shadow line should be filtered out, leaving 2 real movements
        assert len(movements) == 2
        assert movements[0]["fecha"] == "2025-03-09"
        assert movements[1]["fecha"] == "2025-03-15"

    @patch("pdfplumber.open")
    def test_should_skip_noise_lines(self, mock_open):
        text = self._build_santander_pdf_text(
            "09-MAR-2025 1234 SPEI RECIBIDO 5,000.00 15,000.00\n"
            "GAT NOMINAL 5.5%\n"
            "15-MAR-2025 5678 PAGO SERVICIO 1,000.00 14,000.00"
        )
        mock_pdf = _make_mock_pdf([text])
        mock_open.return_value = mock_pdf

        movements = parse_santander("/fake/santander.pdf")
        # GAT NOMINAL is noise; should be skipped (not appended to movement 1)
        assert len(movements) == 2
        assert "GAT NOMINAL" not in movements[0]["descripcion"]

    @patch("pdfplumber.open")
    def test_should_handle_spaced_table_header(self, mock_open):
        text = (
            "BANCO SANTANDER MEXICO\n"
            "PERIODO DEL 01-MAR-2025 AL 31-MAR-2025\n"
            "SALDO FINAL DEL PERIODO ANTERIOR: $10,000.00\n"
            "DETALLE DE MOVIMIENTOS\n"
            "F E C H A  F O L I O  DESCRIPCION DEPOSITO RETIRO SALDO\n"
            "09-MAR-2025 1234 DEPOSITO EN EFECTIVO 5,000.00 15,000.00\n"
            "TOTAL DE MOVIMIENTOS 1"
        )
        mock_pdf = _make_mock_pdf([text])
        mock_open.return_value = mock_pdf

        movements = parse_santander("/fake/santander.pdf")
        assert len(movements) == 1

    @patch("pdfplumber.open")
    def test_should_handle_three_amounts(self, mock_open):
        # Three amounts: DEPOSITO RETIRO SALDO
        text = self._build_santander_pdf_text(
            "09-MAR-2025 1234 DEPOSITO EN EFECTIVO 5,000.00 0.00 15,000.00"
        )
        mock_pdf = _make_mock_pdf([text])
        mock_open.return_value = mock_pdf

        movements = parse_santander("/fake/santander.pdf")
        assert len(movements) == 1
        m = movements[0]
        assert m["deposito"] == Decimal("5000.00")
        assert m["saldo"] == Decimal("15000.00")

    @patch("pdfplumber.open")
    def test_should_have_standard_keys(self, mock_open):
        text = self._build_santander_pdf_text(
            "09-MAR-2025 1234 SPEI RECIBIDO 5,000.00 15,000.00"
        )
        mock_pdf = _make_mock_pdf([text])
        mock_open.return_value = mock_pdf

        movements = parse_santander("/fake/santander.pdf")
        required_keys = {"fecha", "descripcion", "deposito", "retiro", "saldo", "referencia"}
        assert required_keys.issubset(movements[0].keys())

    @patch("pdfplumber.open")
    def test_should_include_raw_line(self, mock_open):
        text = self._build_santander_pdf_text(
            "09-MAR-2025 1234 SPEI RECIBIDO 5,000.00 15,000.00"
        )
        mock_pdf = _make_mock_pdf([text])
        mock_open.return_value = mock_pdf

        movements = parse_santander("/fake/santander.pdf")
        assert "raw_line" in movements[0]
        assert "09-MAR-2025" in movements[0]["raw_line"]

    @patch("pdfplumber.open")
    def test_should_handle_multi_page_pdf(self, mock_open):
        page1 = (
            "BANCO SANTANDER MEXICO\n"
            "PERIODO DEL 01-MAR-2025 AL 31-MAR-2025\n"
            "SALDO FINAL DEL PERIODO ANTERIOR: $10,000.00\n"
            "DETALLE DE MOVIMIENTOS\n"
            "FECHA FOLIO DESCRIPCION DEPOSITO RETIRO SALDO\n"
            "01-MAR-2025 1001 SPEI RECIBIDO 5,000.00 15,000.00"
        )
        page2 = (
            "15-MAR-2025 1002 PAGO SERVICIO 1,000.00 14,000.00\n"
            "TOTAL DE MOVIMIENTOS 2"
        )
        mock_pdf = _make_mock_pdf([page1, page2])
        mock_open.return_value = mock_pdf

        movements = parse_santander("/fake/santander.pdf")
        assert len(movements) == 2

    @patch("pdfplumber.open")
    def test_should_handle_movement_with_one_amount_deposit(self, mock_open):
        text = self._build_santander_pdf_text(
            "09-MAR-2025 1234 DEPOSITO EN EFECTIVO 5,000.00"
        )
        mock_pdf = _make_mock_pdf([text])
        mock_open.return_value = mock_pdf

        movements = parse_santander("/fake/santander.pdf")
        assert len(movements) == 1
        assert movements[0]["deposito"] == Decimal("5000.00")
        assert movements[0]["retiro"] is None
        assert movements[0]["saldo"] is None

    @patch("pdfplumber.open")
    def test_should_handle_movement_with_one_amount_retiro(self, mock_open):
        text = self._build_santander_pdf_text(
            "09-MAR-2025 1234 PAGO TARJETA CREDITO 3,000.00"
        )
        mock_pdf = _make_mock_pdf([text])
        mock_open.return_value = mock_pdf

        movements = parse_santander("/fake/santander.pdf")
        assert len(movements) == 1
        assert movements[0]["retiro"] == Decimal("3000.00")
        assert movements[0]["deposito"] is None
