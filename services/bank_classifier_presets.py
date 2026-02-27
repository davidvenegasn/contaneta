"""
Presets de clasificación para movimientos bancarios (Banorte).
Solo runtime; sin DB. Ajustables para depuración y modos conservador/agresivo.
"""
from typing import Any

# Keywords que disparan método TARJETA
KEYWORDS_TARJETA = [
    "TARJETA DE CRED",
    "TARJETA DE CRÉDITO",
    "PAGO CONCENTRACION",
    "PAGO CONCENTRACIÓN",
    "AMERICAN EXPRES",
    "AMERICAN EXPRESS",
    "TDC",
]

# Keywords que disparan categoría IMPUESTOS
KEYWORDS_IMPUESTO = [
    "PAGO REFERENCIADO",
    "IMPUESTO",
    "SAT",
    "HACIENDA",
]

# Mapa comercio -> (categoria, bucket). Si el texto contiene la clave, se sugiere esa clasificación.
MERCHANT_MAP: dict[str, tuple[str, str]] = {
    "OXXO": ("ALIMENTOS", "PERSONAL"),
    "AMEX": ("FINANCIERO_PAGO_TARJETA", "FINANCIERO"),
    "AMERICAN EXPRESS": ("FINANCIERO_PAGO_TARJETA", "FINANCIERO"),
    "PROFUTURO": ("OTROS", "PERSONAL"),
    "AFORE": ("OTROS", "PERSONAL"),
}

# Palabras que sugieren uso personal (bucket PERSONAL por defecto en modo agresivo)
PERSONAL_HINT_WORDS = [
    "MESADA",
    "AYUDA",
    "PRESTAMO",
    "PRÉSTAMO",
    "FAMILIA",
    "PAGO PERSONAL",
]

PRESET_CONSERVATIVE = "conservative"
PRESET_AGGRESSIVE = "aggressive"


def get_preset(name: str) -> dict[str, Any]:
    """
    Devuelve la configuración del preset para clasificación.
    - conservative: más needs_review=True, bucket DESCONOCIDO cuando hay duda.
    - aggressive: más needs_review=False cuando la regla es clara, bucket PERSONAL por defecto en SPEI/OTROS.
    """
    if name == PRESET_AGGRESSIVE:
        return {
            "default_bucket_unknown": "PERSONAL",
            "default_needs_review_spei": False,
            "confidence_penalty_otros": -10,
        }
    # conservative (default)
    return {
        "default_bucket_unknown": "DESCONOCIDO",
        "default_needs_review_spei": True,
        "confidence_penalty_otros": -20,
    }
