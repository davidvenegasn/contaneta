"""Tests for BBVA bank statement parser."""
from __future__ import annotations

import os
import sys
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("APP_DB_PATH", "/tmp/test_parser_bbva_unused.db")
os.environ.setdefault("SESSION_SECRET", "test-secret-bbva")

from services.bank.parsers.bbva import parse_bbva  # noqa: E402

SAMPLES_DIR = ROOT / "samples" / "bank_statements" / "bbva"


def _check_movements(movements: list):
    """Common assertions for all valid BBVA statement PDFs."""
    assert len(movements) > 0, "Expected at least 1 movement"
    for m in movements:
        # All movements must have a valid date
        assert m.get("fecha") is not None, f"Movement missing fecha: {m}"
        assert len(m["fecha"]) == 10, f"Invalid date format: {m['fecha']}"
        # Amounts must be Decimal or None
        for field in ("deposito", "retiro", "saldo"):
            val = m.get(field)
            assert val is None or isinstance(val, Decimal), f"{field} should be Decimal or None, got {type(val)}: {val}"
    # At least some financial activity
    total_dep = sum(float(m.get("deposito") or 0) for m in movements)
    total_ret = sum(float(m.get("retiro") or 0) for m in movements)
    assert total_dep > 0 or total_ret > 0, "Expected at least some financial activity"


def test_bbva_coahuila_2016():
    pdf = SAMPLES_DIR / "bbva_coahuila_2016.pdf"
    if not pdf.exists():
        pytest.skip("Sample PDF not available")
    movements = parse_bbva(str(pdf))
    _check_movements(movements)
    assert len(movements) >= 40, f"Expected ~43 movements, got {len(movements)}"


@pytest.mark.skip(reason="Investment fund document, not a transactional statement")
def test_bbva_fondos_inversion():
    pdf = SAMPLES_DIR / "bbva_fondos_inversion.pdf"
    if not pdf.exists():
        pytest.skip("Sample PDF not available")
    movements = parse_bbva(str(pdf))
    assert len(movements) == 0


def test_bbva_jalisco_2021_05():
    pdf = SAMPLES_DIR / "bbva_jalisco_2021_05.pdf"
    if not pdf.exists():
        pytest.skip("Sample PDF not available")
    movements = parse_bbva(str(pdf))
    _check_movements(movements)
    assert len(movements) >= 15, f"Expected ~19 movements, got {len(movements)}"


def test_bbva_jalisco_2022_01():
    pdf = SAMPLES_DIR / "bbva_jalisco_2022_01.pdf"
    if not pdf.exists():
        pytest.skip("Sample PDF not available")
    movements = parse_bbva(str(pdf))
    _check_movements(movements)
    assert len(movements) >= 10, f"Expected ~12 movements, got {len(movements)}"
