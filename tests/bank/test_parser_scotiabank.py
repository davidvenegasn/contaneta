"""Tests for Scotiabank statement parser."""
import os
from decimal import Decimal

import pytest

SAMPLES_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "samples", "bank_statements", "scotiabank")


def _have_samples():
    return os.path.isdir(SAMPLES_DIR) and any(f.endswith(".pdf") for f in os.listdir(SAMPLES_DIR))


@pytest.mark.skipif(not _have_samples(), reason="No Scotiabank sample PDFs")
class TestScotiabankParser:
    def test_pv_2024_01(self):
        from services.bank.parsers.scotiabank import parse_scotiabank
        movs = parse_scotiabank(os.path.join(SAMPLES_DIR, "scotiabank_pv_2024_01.pdf"))
        assert len(movs) == 1
        assert movs[0]["fecha"] == "2024-01-31"
        assert movs[0]["deposito"] == Decimal("218752.00")
        assert movs[0]["saldo"] == Decimal("22864420.47")

    def test_seapal_marzo(self):
        from services.bank.parsers.scotiabank import parse_scotiabank
        movs = parse_scotiabank(os.path.join(SAMPLES_DIR, "scotiabank_seapal_marzo.pdf"))
        assert len(movs) == 48
        assert all(m["fecha"] for m in movs)
        dep_total = sum(m["deposito"] for m in movs if m["deposito"])
        ret_total = sum(m["retiro"] for m in movs if m["retiro"])
        assert dep_total == Decimal("101900.70")
        assert ret_total == Decimal("97550.34")

    def test_guadalajara_2021_first_account_only(self):
        """Multi-account PDF — only first account (1 interest payment)."""
        from services.bank.parsers.scotiabank import parse_scotiabank
        path = os.path.join(SAMPLES_DIR, "scotiabank_guadalajara_2021_08.pdf")
        if not os.path.exists(path):
            pytest.skip("Guadalajara sample not available")
        movs = parse_scotiabank(path)
        assert len(movs) == 1
        assert movs[0]["fecha"] == "2021-08-31"
        assert movs[0]["deposito"] == Decimal("6395.77")
