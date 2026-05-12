"""Tests for Banco Azteca statement parser."""
import os
from decimal import Decimal

import pytest

SAMPLES_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "samples", "bank_statements", "azteca")


def _have_samples():
    return os.path.isdir(SAMPLES_DIR) and any(f.endswith(".pdf") for f in os.listdir(SAMPLES_DIR))


@pytest.mark.skipif(not _have_samples(), reason="No Azteca sample PDFs")
class TestAztecaParser:
    def test_guadalajara_2022_04(self):
        """Multi-account PDF — only first account (9 transactions)."""
        from services.bank.parsers.azteca import parse_azteca
        movs = parse_azteca(os.path.join(SAMPLES_DIR, "azteca_guadalajara_2022_04.pdf"))
        assert len(movs) == 9
        dep_total = sum(m["deposito"] for m in movs if m["deposito"])
        ret_total = sum(m["retiro"] for m in movs if m["retiro"])
        assert dep_total == Decimal("7381644.55")
        assert ret_total == Decimal("7385758.52")
        assert all(m["fecha"] for m in movs)

    def test_seapal_2024_02(self):
        """Multi-account PDF — only first account (3 transactions)."""
        from services.bank.parsers.azteca import parse_azteca
        movs = parse_azteca(os.path.join(SAMPLES_DIR, "azteca_seapal_2024_02.pdf"))
        assert len(movs) == 3
        assert movs[0]["deposito"] == Decimal("37914.80")
        assert movs[1]["retiro"] == Decimal("10000000.00")
        assert movs[2]["saldo"] == Decimal("0.00")

    def test_seapal_2025_02(self):
        """21 deposits, 0 retiros."""
        from services.bank.parsers.azteca import parse_azteca
        movs = parse_azteca(os.path.join(SAMPLES_DIR, "azteca_seapal_2025_02.pdf"))
        assert len(movs) == 21
        dep_total = sum(m["deposito"] for m in movs if m["deposito"])
        ret_total = sum(m["retiro"] for m in movs if m["retiro"])
        assert dep_total == Decimal("30154.56")
        assert ret_total == Decimal("0")
        # Verify .01 amount handled correctly
        assert movs[-1]["deposito"] == Decimal("0.01")
