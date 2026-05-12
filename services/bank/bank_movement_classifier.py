"""
Clasificación y normalización de movimientos bancarios (Fase 4).
Reglas: pago TDC, traspaso interno, comisiones; duplicate_hash.
"""
from __future__ import annotations

import re
from typing import Any

from services.bank.bank_preview_models import compute_dedupe_fingerprint


def normalize_description(raw: str) -> str:
    """Normaliza descripción: mayúsculas, quita espacios dobles, límite razonable."""
    if not raw or not isinstance(raw, str):
        return ""
    s = re.sub(r"\s+", " ", (raw or "").strip().upper())
    return s[:2000]


def compute_duplicate_hash(mov: dict[str, Any]) -> str:
    """Hash para detección de duplicados (fecha + monto + concepto)."""
    return compute_dedupe_fingerprint(mov)


def classify_movement(mov: dict[str, Any]) -> dict[str, Any]:
    """
    Clasifica un movimiento: movement_type, business_effect, tax_effect, requires_cfdi.
    Devuelve dict con esas claves para actualizar el movimiento.
    """
    out: dict[str, Any] = {
        "movement_type": "other",
        "business_effect": "expense",
        "tax_effect": "unknown",
        "requires_cfdi": 0,
    }
    tipo = (mov.get("tipo_movimiento") or mov.get("tipo") or "").upper()
    desc = (mov.get("raw_text_normalized") or mov.get("descripcion") or mov.get("concepto_resumen") or "").upper()
    categoria = (mov.get("categoria_sugerida") or mov.get("categoria") or "").upper()
    metodo = (mov.get("canal") or mov.get("metodo_hint") or "").upper()

    if tipo == "INGRESO":
        out["business_effect"] = "income"
    elif tipo == "GASTO":
        out["business_effect"] = "expense"
    else:
        out["business_effect"] = "neutral"

    if mov.get("es_pago_tarjeta_probable") or "PAGO TARJETA" in desc or "PAGO CONCENTRACION" in desc or "TARJETA" in metodo:
        out["movement_type"] = "card_payment"
        out["requires_cfdi"] = 0
    elif mov.get("es_transferencia_propia_probable") or "TRASPASO" in desc or "SPEI A " in desc or "SPEI DE " in desc:
        out["movement_type"] = "internal_transfer"
        out["requires_cfdi"] = 0
    elif "COMISION" in desc or "COMISIONES" in desc or "IVA COMISION" in desc:
        out["movement_type"] = "fee"
        out["requires_cfdi"] = 1
    elif "NOMINA" in desc or "NOMINA" in categoria:
        out["movement_type"] = "payroll"
        out["requires_cfdi"] = 1
    elif tipo == "GASTO" and float(mov.get("monto_retiro") or mov.get("retiro") or 0) >= 0.01:
        out["movement_type"] = "payment"
        out["requires_cfdi"] = 1
    elif tipo == "INGRESO":
        out["movement_type"] = "income"
        out["requires_cfdi"] = 0

    if out["requires_cfdi"] and out["business_effect"] == "expense":
        out["tax_effect"] = "deductible_candidate"
    elif out["business_effect"] == "income":
        out["tax_effect"] = "taxable_income"
    else:
        out["tax_effect"] = "neutral"

    return out
