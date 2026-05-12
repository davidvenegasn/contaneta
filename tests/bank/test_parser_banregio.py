"""Tests for Banregio statement parser."""
import os
from decimal import Decimal

import pytest

SAMPLES_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "samples", "bank_statements", "banregio")


def _have_samples():
    return os.path.isdir(SAMPLES_DIR) and any(f.endswith(".pdf") for f in os.listdir(SAMPLES_DIR))


@pytest.mark.skipif(not _have_samples(), reason="No Banregio sample PDFs")
class TestBanregioParser:
    def test_guadalajara_2021_04(self):
        from services.bank.parsers.banregio import parse_banregio
        movs = parse_banregio(os.path.join(SAMPLES_DIR, "banregio_guadalajara_2021_04.pdf"))
        assert len(movs) == 1
        assert movs[0]["fecha"] == "2021-04-30"
        assert movs[0]["deposito"] == Decimal("0.72")
        assert movs[0]["saldo"] == Decimal("1348.84")

    def test_tlajomulco_2020_06(self):
        from services.bank.parsers.banregio import parse_banregio
        movs = parse_banregio(os.path.join(SAMPLES_DIR, "banregio_tlajomulco_2020_06.pdf"))
        assert len(movs) == 1
        assert movs[0]["fecha"] == "2020-06-30"
        assert movs[0]["deposito"] == Decimal("0.33")
        assert movs[0]["saldo"] == Decimal("297.96")

    @pytest.mark.skip(reason="Image-only PDF — no extractable text")
    def test_guadalajara_2021_10(self):
        pass
