"""Tests for CFDI TipoRelacion labels and signed amount semantics."""
import pytest

from services.sat.cfdi_relacion_labels import (
    label_for_received,
    badge_color,
    signed_amount,
    signed_multiplier,
    compute_net_totals,
    TIPO_RELACION_LABELS,
)


# ── label_for_received ────────────────────────────────────────────────────

def test_should_return_ingreso_for_tipo_i():
    assert label_for_received("I", None) == "Ingreso"


def test_should_return_nomina_for_tipo_n():
    assert label_for_received("N", None) == "Nómina"


def test_should_return_pago_rep_for_tipo_p():
    assert label_for_received("P", None) == "Pago (REP)"


def test_should_return_traslado_for_tipo_t():
    assert label_for_received("T", None) == "Traslado"


def test_should_return_nota_credito_for_egreso_01():
    assert label_for_received("E", "01") == "Nota de crédito"


def test_should_return_devolucion_for_egreso_03():
    assert label_for_received("E", "03") == "Devolución"


def test_should_return_sustitucion_for_egreso_04():
    assert label_for_received("E", "04") == "Sustitución"


def test_should_return_anticipo_aplicado_for_egreso_07():
    assert label_for_received("E", "07") == "Anticipo aplicado"


def test_should_return_egreso_fallback_when_no_relacion():
    assert label_for_received("E", None) == "Egreso"


def test_should_handle_lowercase_tipo():
    assert label_for_received("e", "01") == "Nota de crédito"
    assert label_for_received("i", None) == "Ingreso"


# ── badge_color ───────────────────────────────────────────────────────────

def test_should_return_info_for_ingreso():
    assert badge_color("I", None) == "info"


def test_should_return_warn_for_nota_credito():
    assert badge_color("E", "01") == "warn"


def test_should_return_ppd_for_anticipo():
    assert badge_color("E", "07") == "ppd"


def test_should_return_neutral_for_sustitucion():
    assert badge_color("E", "04") == "neutral"


# ── signed_amount ─────────────────────────────────────────────────────────

def test_should_sum_ingreso():
    assert signed_amount(100.0, "I", None) == 100.0


def test_should_subtract_nota_credito():
    assert signed_amount(100.0, "E", "01") == -100.0


def test_should_subtract_devolucion():
    assert signed_amount(100.0, "E", "03") == -100.0


def test_should_subtract_anticipo_aplicado():
    assert signed_amount(100.0, "E", "07") == -100.0


def test_should_zero_sustitucion():
    assert signed_amount(100.0, "E", "04") == 0.0


def test_should_zero_traslado():
    assert signed_amount(100.0, "E", "05") == 0.0


def test_should_zero_pago():
    assert signed_amount(100.0, "P", None) == 0.0


def test_should_sum_nomina():
    assert signed_amount(100.0, "N", None) == 100.0


def test_should_subtract_egreso_unknown_conservador():
    """Unknown Egreso without TipoRelacion should subtract (conservative)."""
    assert signed_amount(100.0, "E", None) == -100.0


def test_should_subtract_egreso_unknown_tipo_relacion():
    """Unknown TipoRelacion on Egreso defaults to negative (conservative)."""
    assert signed_amount(100.0, "E", "99") == -100.0


# ── signed_multiplier ────────────────────────────────────────────────────

def test_signed_multiplier_ingreso():
    assert signed_multiplier("I", None) == 1


def test_signed_multiplier_nota_credito():
    assert signed_multiplier("E", "01") == -1


def test_signed_multiplier_devolucion():
    assert signed_multiplier("E", "03") == -1


def test_signed_multiplier_anticipo():
    assert signed_multiplier("E", "07") == -1


def test_signed_multiplier_sustitucion():
    assert signed_multiplier("E", "04") == 0


def test_signed_multiplier_pago():
    assert signed_multiplier("P", None) == 0


def test_signed_multiplier_traslado():
    assert signed_multiplier("T", None) == 1


def test_signed_multiplier_nomina():
    assert signed_multiplier("N", None) == 1


# ── compute_net_totals ───────────────────────────────────────────────────

def _row(tc, tr, sub, iva, ret, total):
    return {
        "tipo_comprobante": tc, "tipo_relacion": tr,
        "subtotal": sub, "impuestos": iva, "retenciones": ret, "total": total,
    }


def test_should_compute_net_with_nc():
    """NC should subtract from net totals."""
    rows = [
        _row("I", None, 1000, 160, 0, 1160),
        _row("E", "01", 200, 32, 0, 232),
    ]
    net = compute_net_totals(rows)
    assert net["subtotal"] == pytest.approx(800.0)
    assert net["iva"] == pytest.approx(128.0)
    assert net["total"] == pytest.approx(928.0)
    assert net["ingresos_n"] == 1
    assert net["notas_n"] == 1


def test_should_compute_net_with_anticipo():
    """Anticipo aplicado (07) should subtract from net totals."""
    rows = [
        _row("I", None, 500, 80, 0, 580),
        _row("E", "07", 100, 16, 0, 116),
    ]
    net = compute_net_totals(rows)
    assert net["subtotal"] == pytest.approx(400.0)
    assert net["total"] == pytest.approx(464.0)
    assert net["anticipos_n"] == 1
    assert net["anticipos_total"] == pytest.approx(116.0)


def test_should_skip_sustitucion():
    """Sustitución (04) is neutral — multiplier=0."""
    rows = [
        _row("I", None, 1000, 160, 0, 1160),
        _row("E", "04", 500, 80, 0, 580),
    ]
    net = compute_net_totals(rows)
    assert net["subtotal"] == pytest.approx(1000.0)
    assert net["total"] == pytest.approx(1160.0)


def test_should_skip_pagos():
    """Pagos (P) don't affect net totals."""
    rows = [
        _row("I", None, 1000, 160, 0, 1160),
        _row("P", None, 1000, 0, 0, 1000),
    ]
    net = compute_net_totals(rows)
    assert net["subtotal"] == pytest.approx(1000.0)
    assert net["total"] == pytest.approx(1160.0)


def test_should_handle_empty_rows():
    net = compute_net_totals([])
    assert net["subtotal"] == 0.0
    assert net["total"] == 0.0
    assert net["ingresos_n"] == 0


def test_should_bucket_correctly():
    """Verify breakdown buckets match expected counts and totals."""
    rows = [
        _row("I", None, 100, 16, 0, 116),
        _row("I", None, 200, 32, 0, 232),
        _row("E", "01", 50, 8, 0, 58),
        _row("E", "07", 30, 4.8, 0, 34.8),
    ]
    net = compute_net_totals(rows)
    assert net["ingresos_n"] == 2
    assert net["ingresos_total"] == pytest.approx(348.0)
    assert net["notas_n"] == 1
    assert net["notas_total"] == pytest.approx(58.0)
    assert net["anticipos_n"] == 1
    assert net["anticipos_total"] == pytest.approx(34.8)


# ── catalog completeness ─────────────────────────────────────────────────

def test_tipo_relacion_catalog_has_01_through_09():
    for code in ("01", "02", "03", "04", "05", "06", "07", "08", "09"):
        assert code in TIPO_RELACION_LABELS, f"Missing {code}"
