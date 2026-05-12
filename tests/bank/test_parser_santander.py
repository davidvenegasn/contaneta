"""Tests for Santander statement parser."""
import os
import pytest

SAMPLES_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "samples", "bank_statements", "santander")


def _have_samples():
    return os.path.isdir(SAMPLES_DIR) and any(f.endswith(".pdf") for f in os.listdir(SAMPLES_DIR))


@pytest.mark.skipif(not _have_samples(), reason="No Santander sample PDFs")
class TestSantanderParser:
    def test_pv_2024_05(self):
        from services.bank.parsers.santander import parse_santander
        movs = parse_santander(os.path.join(SAMPLES_DIR, "santander_pv_2024_05.pdf"))
        assert len(movs) == 8
        assert all(m["fecha"] for m in movs)
        assert all(m["fecha"].startswith("2024-05") for m in movs)
        # All should have saldo
        assert all(m["saldo"] is not None for m in movs)

    def test_pv_2025_03(self):
        from services.bank.parsers.santander import parse_santander
        movs = parse_santander(os.path.join(SAMPLES_DIR, "santander_pv_2025_03.pdf"))
        assert len(movs) >= 400  # 503 expected
        assert all(m["fecha"] for m in movs)
        assert all(m["fecha"].startswith("2025-03") for m in movs)

    def test_guadalajara_2021_08_ocr(self):
        """OCR-heavy PDF — verify date parsing handles AG0/AGD artifacts."""
        from services.bank.parsers.santander import parse_santander
        path = os.path.join(SAMPLES_DIR, "santander_guadalajara_2021_08.pdf")
        if not os.path.exists(path):
            pytest.skip("Guadalajara sample not available")
        movs = parse_santander(path)
        assert len(movs) >= 200  # 324 expected
        dates_ok = sum(1 for m in movs if m.get("fecha"))
        assert dates_ok == len(movs), f"All movements should have valid dates, got {dates_ok}/{len(movs)}"

    def test_shadow_line_dedup(self):
        """Verify the shadow line dedup function."""
        from services.bank.parsers.santander import _dedupe_shadow_lines
        lines = [
            (1, 1, "03-MAR-2025 Normal line"),
            (1, 2, "0033--MMAARR--22002255 Shadow line"),  # doubled chars
            (1, 3, "Another normal line"),
        ]
        result = _dedupe_shadow_lines(lines)
        assert len(result) == 2
        assert result[0][2] == "03-MAR-2025 Normal line"
        assert result[1][2] == "Another normal line"

    def test_ocr_month_fix(self):
        """Verify OCR month substitutions work."""
        from services.bank.parsers.santander import _OCR_MONTH_FIX
        assert _OCR_MONTH_FIX["AG0"] == "AGO"
        assert _OCR_MONTH_FIX["AGD"] == "AGO"
        assert _OCR_MONTH_FIX["0CT"] == "OCT"
