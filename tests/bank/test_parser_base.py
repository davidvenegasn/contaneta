"""Tests for shared parser utilities."""
from __future__ import annotations

import os
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

if not os.environ.get("APP_DB_PATH"):
    os.environ["APP_DB_PATH"] = "/tmp/test_parser_base_unused.db"
if not os.environ.get("SESSION_SECRET"):
    os.environ["SESSION_SECRET"] = "test-secret-parser-base"

from services.bank.parsers._base import (  # noqa: E402
    norm_text,
    parse_amount,
    parse_date_es,
    strip_accents,
)


def test_strip_accents():
    assert strip_accents("Depósito") == "Deposito"
    assert strip_accents("año") == "ano"
    assert strip_accents("") == ""
    assert strip_accents("ABC") == "ABC"


def test_norm_text():
    assert norm_text("  Depósito   bancario  ") == "DEPOSITO BANCARIO"
    assert norm_text("") == ""


def test_parse_amount_basic():
    assert parse_amount("1,234.56") == Decimal("1234.56")
    assert parse_amount("10,000.00") == Decimal("10000.00")
    assert parse_amount("0.01") == Decimal("0.01")
    assert parse_amount("$1,234.56") == Decimal("1234.56")


def test_parse_amount_negative():
    assert parse_amount("-1,234.56") == Decimal("-1234.56")


def test_parse_amount_invalid():
    assert parse_amount("") is None
    assert parse_amount("abc") is None
    assert parse_amount("123") is None  # no decimals


def test_parse_date_es_banorte():
    assert parse_date_es("01-ENE-26") == date(2026, 1, 1)
    assert parse_date_es("15-DIC-25") == date(2025, 12, 15)
    assert parse_date_es("28-FEB-24") == date(2024, 2, 28)


def test_parse_date_es_slash():
    assert parse_date_es("01/01/2026") == date(2026, 1, 1)
    assert parse_date_es("15/12/25") == date(2025, 12, 15)


def test_parse_date_es_dash_numeric():
    assert parse_date_es("01-01-2026") == date(2026, 1, 1)


def test_parse_date_es_full_month():
    assert parse_date_es("01 de enero 2026") == date(2026, 1, 1)
    assert parse_date_es("15 de diciembre de 2025") == date(2025, 12, 15)


def test_parse_date_es_iso():
    assert parse_date_es("2026-01-15") == date(2026, 1, 15)


def test_parse_date_es_invalid():
    assert parse_date_es("") is None
    assert parse_date_es("not a date") is None
    assert parse_date_es("32/13/2026") is None  # invalid day/month
