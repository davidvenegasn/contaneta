"""Tests for BanBajío statement parser."""
import os
from decimal import Decimal

import pytest

SAMPLES_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "samples", "bank_statements", "banbajio")


def _have_samples():
    return os.path.isdir(SAMPLES_DIR) and any(f.endswith(".pdf") for f in os.listdir(SAMPLES_DIR))


@pytest.mark.skipif(not _have_samples(), reason="No BanBajío sample PDFs")
class TestBanBajioParser:
    def test_guadalajara_2019_04(self):
        from services.bank.parsers.banbajio import parse_banbajio
        movs = parse_banbajio(os.path.join(SAMPLES_DIR, "banbajio_guadalajara_2019_04.pdf"))
        assert len(movs) == 2
        assert all(m["fecha"] == "2019-04-30" for m in movs)
        ret_total = sum(m["retiro"] for m in movs if m["retiro"])
        assert ret_total == Decimal("147.90")

    @pytest.mark.skip(reason="2024 PDF has reversed text — needs OCR preprocessing")
    def test_tlaquepaque_2024_04(self):
        pass

    @pytest.mark.skip(reason="2021 PDF has severe OCR corruption")
    def test_guadalajara_2021_08(self):
        pass
