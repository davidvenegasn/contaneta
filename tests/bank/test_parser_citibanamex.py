"""Tests for Citibanamex statement parser."""
import os
from decimal import Decimal

import pytest

SAMPLES_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "samples", "bank_statements", "citibanamex")


def _have_samples():
    return os.path.isdir(SAMPLES_DIR) and any(f.endswith(".pdf") for f in os.listdir(SAMPLES_DIR))


@pytest.mark.skipif(not _have_samples(), reason="No Citibanamex sample PDFs")
class TestCitibanamexParser:
    def test_pv_2023_04(self):
        from services.bank.parsers.citibanamex import parse_citibanamex
        movs = parse_citibanamex(os.path.join(SAMPLES_DIR, "citibanamex_pv_2023_04.pdf"))
        assert len(movs) == 11
        assert all(m["fecha"] for m in movs)
        assert all(m["fecha"].startswith("2023-04") for m in movs)
        dep_total = sum(m["deposito"] for m in movs if m["deposito"])
        ret_total = sum(m["retiro"] for m in movs if m["retiro"])
        assert dep_total == Decimal("231303.75")
        assert ret_total == Decimal("2558.38")

    def test_pv_2024_02(self):
        from services.bank.parsers.citibanamex import parse_citibanamex
        movs = parse_citibanamex(os.path.join(SAMPLES_DIR, "citibanamex_pv_2024_02.pdf"))
        assert len(movs) == 9
        assert all(m["fecha"] for m in movs)
        dep_total = sum(m["deposito"] for m in movs if m["deposito"])
        ret_total = sum(m["retiro"] for m in movs if m["retiro"])
        assert dep_total == Decimal("117265.28")
        assert ret_total == Decimal("9245734.72")

    def test_seapal_2026_02_first_account_only(self):
        """Multi-account PDF — only parse first account."""
        from services.bank.parsers.citibanamex import parse_citibanamex
        movs = parse_citibanamex(os.path.join(SAMPLES_DIR, "citibanamex_seapal_2026_02.pdf"))
        assert len(movs) == 34
        assert all(m["fecha"] for m in movs)
        # All dates should be Feb 2026
        assert all(m["fecha"].startswith("2026-02") for m in movs)
        dep_total = sum(m["deposito"] for m in movs if m["deposito"])
        ret_total = sum(m["retiro"] for m in movs if m["retiro"])
        assert dep_total == Decimal("326880.00")
        assert ret_total == Decimal("1118.82")

    def test_column_classification(self):
        """Verify amount column classification by x-position."""
        from services.bank.parsers.citibanamex import _RETIROS_MAX_X, _DEPOSITOS_MAX_X
        # Retiros are at x0 ~286-298 (< 330)
        assert _RETIROS_MAX_X == 330
        # Depositos are at x0 ~354-371 (< 415)
        assert _DEPOSITOS_MAX_X == 415
