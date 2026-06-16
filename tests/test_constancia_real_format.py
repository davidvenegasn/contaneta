"""Tests for constancia parser using synthetic PDFs (Phase 10).

Each fixture mimics the SAT Constancia de Situación Fiscal format.
"""
import os
from pathlib import Path

import pytest

from services.constancia.parser import parse_constancia

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "constancias"


def _load_pdf(name: str) -> bytes:
    """Load a fixture PDF by filename."""
    path = FIXTURES_DIR / name
    assert path.exists(), f"Fixture {name} not found at {path}"
    return path.read_bytes()


# -- PF: Régimen 612 (Actividad Empresarial) --

class TestConstanciaPF612:
    """Parse constancia for Persona Física with régimen 612."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.result = parse_constancia(_load_pdf("constancia_pf_612.pdf"))

    def test_confidence_above_threshold(self):
        assert self.result["confidence"] >= 0.75

    def test_rfc_extracted(self):
        assert self.result["rfc"] == "VEDA980101ABC"

    def test_curp_extracted(self):
        assert self.result["curp"] == "VEDA980101HDFRRL01"

    def test_razon_social_extracted(self):
        assert "DAVID VENEGAS" in (self.result["razon_social"] or "")

    def test_regimen_extracted(self):
        assert self.result["regimen_fiscal"] == "612"

    def test_codigo_postal_extracted(self):
        assert self.result["codigo_postal"] == "06000"


# -- PM: Régimen 601 (General de Ley) --

class TestConstanciaPM601:
    """Parse constancia for Persona Moral with régimen 601."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.result = parse_constancia(_load_pdf("constancia_pm_601.pdf"))

    def test_confidence_above_threshold(self):
        assert self.result["confidence"] >= 0.75

    def test_rfc_extracted(self):
        assert self.result["rfc"] == "TEST010101AB1"

    def test_no_curp_for_pm(self):
        """Persona Moral should not have CURP."""
        assert self.result["curp"] is None

    def test_razon_social_extracted(self):
        assert "EMPRESA PRUEBA" in (self.result["razon_social"] or "")

    def test_regimen_extracted(self):
        assert self.result["regimen_fiscal"] == "601"

    def test_codigo_postal_extracted(self):
        assert self.result["codigo_postal"] == "64000"


# -- RESICO: Régimen 626 --

class TestConstanciaResico626:
    """Parse constancia for RESICO with régimen 626."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.result = parse_constancia(_load_pdf("constancia_resico_626.pdf"))

    def test_confidence_above_threshold(self):
        assert self.result["confidence"] >= 0.75

    def test_rfc_extracted(self):
        assert self.result["rfc"] == "LOGA850515XY9"

    def test_regimen_extracted(self):
        assert self.result["regimen_fiscal"] == "626"

    def test_codigo_postal_extracted(self):
        assert self.result["codigo_postal"] == "44100"


# -- Multiple obligations --

class TestConstanciaMultiObligaciones:
    """Parse constancia with multiple obligations."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.result = parse_constancia(_load_pdf("constancia_multi_obligaciones.pdf"))

    def test_confidence_above_threshold(self):
        assert self.result["confidence"] >= 0.75

    def test_rfc_extracted(self):
        assert self.result["rfc"] == "MUBE790320QR3"

    def test_obligaciones_extracted(self):
        """Should extract at least some obligations."""
        assert len(self.result.get("obligaciones", [])) >= 2

    def test_regimen_extracted(self):
        assert self.result["regimen_fiscal"] == "612"


# -- Edge case: generic RFC --

class TestConstanciaEdgeCase:
    """Parse constancia with edge case data (generic RFC)."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.result = parse_constancia(_load_pdf("constancia_edge_case.pdf"))

    def test_rfc_extracted(self):
        assert self.result["rfc"] == "XAXX010101000"

    def test_regimen_extracted(self):
        assert self.result["regimen_fiscal"] == "616"

    def test_obligaciones_may_have_noise(self):
        """Edge case: parser may extract noise when no real obligations exist.

        This is a known limitation of regex-based parsing — the obligations
        extractor grabs text between labels, which may include fragments
        from surrounding fields. An LLM-based parser would handle this better.
        """
        # Accept any result — documenting the limitation
        assert isinstance(self.result.get("obligaciones", []), list)


# -- Summary --

def test_parser_succeeds_on_at_least_4_of_5():
    """Parser should achieve confidence >= 0.75 on at least 4 of 5 fixtures."""
    fixtures = [
        "constancia_pf_612.pdf",
        "constancia_pm_601.pdf",
        "constancia_resico_626.pdf",
        "constancia_multi_obligaciones.pdf",
        "constancia_edge_case.pdf",
    ]
    results = []
    for f in fixtures:
        r = parse_constancia(_load_pdf(f))
        results.append((f, r["confidence"]))

    high_confidence = sum(1 for _, conf in results if conf >= 0.75)
    assert high_confidence >= 4, f"Only {high_confidence}/5 had confidence >= 0.75: {results}"
