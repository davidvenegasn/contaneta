"""Unit tests for services.fiscal.calculators."""
import pytest
from services.fiscal.calculators import (
    IVA_RATE,
    calc_iva,
    calc_pfae_general,
    calc_resico_pf,
)


class TestCalcResicoPf:
    """RESICO PF ISR estimation."""

    def test_zero_income(self):
        r = calc_resico_pf(0)
        assert r["isr_estimado"] == 0.0
        assert r["tasa_aplicada"] == 0.0

    def test_negative_income(self):
        r = calc_resico_pf(-500)
        assert r["isr_estimado"] == 0.0

    def test_first_bracket(self):
        # <= 25,000 → 1.00%
        r = calc_resico_pf(20_000)
        assert r["tasa_aplicada"] == 0.01
        assert r["isr_estimado"] == 200.0

    def test_second_bracket(self):
        # 25,001 – 50,000 → 1.10%
        r = calc_resico_pf(40_000)
        assert r["tasa_aplicada"] == 0.011
        assert r["isr_estimado"] == 440.0

    def test_third_bracket(self):
        # 50,001 – 83,333.33 → 1.50%
        r = calc_resico_pf(75_000)
        assert r["tasa_aplicada"] == 0.015
        assert r["isr_estimado"] == 1_125.0

    def test_fourth_bracket(self):
        # 83,333.34 – 208,333.33 → 2.00%
        r = calc_resico_pf(150_000)
        assert r["tasa_aplicada"] == 0.02
        assert r["isr_estimado"] == 3_000.0

    def test_max_bracket(self):
        # > 208,333.33 (up to 3,500,000) → 2.50%
        r = calc_resico_pf(300_000)
        assert r["tasa_aplicada"] == 0.025
        assert r["isr_estimado"] == 7_500.0

    def test_boundary_first(self):
        r = calc_resico_pf(25_000)
        assert r["tasa_aplicada"] == 0.01

    def test_boundary_above_first(self):
        r = calc_resico_pf(25_001)
        assert r["tasa_aplicada"] == 0.011

    def test_has_disclaimer(self):
        r = calc_resico_pf(10_000)
        assert "disclaimer" in r
        assert "SAT 2026" in r["disclaimer"]


class TestCalcPfaeGeneral:
    """PFAE General (Art. 96) ISR estimation."""

    def test_zero_income(self):
        r = calc_pfae_general(0)
        assert r["isr_provisional"] == 0.0

    def test_income_minus_deductions_zero(self):
        r = calc_pfae_general(10_000, deducciones_mes=10_000)
        assert r["isr_provisional"] == 0.0

    def test_low_income(self):
        r = calc_pfae_general(500)
        assert r["isr_provisional"] > 0
        assert r["tasa_marginal"] == 0.0192

    def test_medium_income(self):
        # 50,000 income, 10,000 deductions → base 40,000
        r = calc_pfae_general(50_000, deducciones_mes=10_000)
        assert r["base_gravable"] == 40_000.0
        assert r["isr_provisional"] > 0
        assert r["cuota_fija"] > 0

    def test_retenciones_reduce_isr(self):
        r1 = calc_pfae_general(50_000)
        r2 = calc_pfae_general(50_000, retenciones_isr=2_000)
        assert r2["isr_provisional"] < r1["isr_provisional"]
        assert r2["isr_antes_retenciones"] == r1["isr_antes_retenciones"]

    def test_retenciones_exceed_isr(self):
        # If retenciones > ISR bruto, provisional should be 0
        r = calc_pfae_general(1_000, retenciones_isr=999_999)
        assert r["isr_provisional"] == 0.0

    def test_high_income_bracket(self):
        # 400,000 → top bracket (35%)
        r = calc_pfae_general(400_000)
        assert r["tasa_marginal"] == 0.35

    def test_has_disclaimer(self):
        r = calc_pfae_general(10_000)
        assert "disclaimer" in r


class TestCalcIva:
    """IVA calculation."""

    def test_iva_to_pay(self):
        r = calc_iva(16_000, 8_000)
        assert r["iva_a_pagar"] == 8_000.0
        assert r["saldo_a_favor"] == 0.0

    def test_iva_in_favor(self):
        r = calc_iva(5_000, 10_000)
        assert r["iva_a_pagar"] == 0.0
        assert r["saldo_a_favor"] == 5_000.0

    def test_iva_with_retenido(self):
        r = calc_iva(16_000, 8_000, iva_retenido=3_000)
        assert r["iva_a_pagar"] == 5_000.0

    def test_iva_zero(self):
        r = calc_iva(0, 0)
        assert r["iva_a_pagar"] == 0.0
        assert r["saldo_a_favor"] == 0.0

    def test_iva_rate_constant(self):
        assert IVA_RATE == 0.16

    def test_has_disclaimer(self):
        r = calc_iva(1_000, 500)
        assert "disclaimer" in r
