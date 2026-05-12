# -*- coding: utf-8 -*-
"""
Validación de datos para clientes (RFC, CP, régimen, email) y productos (ClaveProdServ, unidad).
"""
import re
from typing import Optional

# RFC: 12 caracteres (persona moral) o 13 (persona física). Alfanumérico.
# Casos especiales: XAXX010101000, XEXX010101000 (público en general / extranjero).
_RFC_PATTERN = re.compile(r"^[A-Z&Ñ][0-9A-Z&Ñ]{11,12}$")

# CP México: 5 dígitos
_ZIP_PATTERN = re.compile(r"^[0-9]{5}$")

# Régimen fiscal SAT: 3 dígitos (ej. 601, 612, 626)
_TAX_SYSTEM_PATTERN = re.compile(r"^[0-9]{3}$")

# Email básico
_EMAIL_PATTERN = re.compile(
    r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
)

# Clave producto/servicio SAT: 8 dígitos
_PRODUCT_KEY_PATTERN = re.compile(r"^[0-9]{8}$")

# Unidades SAT: 3 caracteres alfanuméricos (E48, H87, MTR, etc.)
_UNIT_KEY_PATTERN = re.compile(r"^[0-9A-Z]{2,3}$")

# Razón social: longitud razonable
LEGAL_NAME_MAX_LEN = 300
DESCRIPTION_MAX_LEN = 255


def validate_rfc(rfc: str) -> Optional[str]:
    """
    Valida formato de RFC (México).
    Retorna None si es válido, o mensaje de error.
    """
    if not rfc or not isinstance(rfc, str):
        return "RFC es obligatorio"
    rfc = rfc.strip().upper()
    if len(rfc) not in (12, 13):
        return "RFC debe tener 12 caracteres (persona moral) o 13 (persona física)"
    if not _RFC_PATTERN.match(rfc):
        return "RFC con formato inválido (solo letras y números)"
    return None


def validate_zip(zip_val: str) -> Optional[str]:
    """C.P. opcional: si se envía, debe ser 5 dígitos."""
    if not zip_val or not zip_val.strip():
        return None
    if not _ZIP_PATTERN.match(zip_val.strip()):
        return "Código postal debe ser 5 dígitos"
    return None


def validate_tax_system(tax_val: str) -> Optional[str]:
    """Régimen fiscal opcional: si se envía, 3 dígitos (código SAT)."""
    if not tax_val or not tax_val.strip():
        return None
    if not _TAX_SYSTEM_PATTERN.match(tax_val.strip()):
        return "Régimen fiscal debe ser un código de 3 dígitos (ej. 601, 612)"
    return None


def validate_email(email: Optional[str]) -> Optional[str]:
    """Email opcional: si se envía, formato válido."""
    if not email or not str(email).strip():
        return None
    if not _EMAIL_PATTERN.match(str(email).strip()):
        return "Formato de correo electrónico inválido"
    return None


def validate_legal_name(legal_name: str) -> Optional[str]:
    """Razón social: obligatoria y longitud máxima."""
    if not legal_name or not legal_name.strip():
        return "Razón social es obligatoria"
    if len(legal_name.strip()) > LEGAL_NAME_MAX_LEN:
        return f"Razón social no puede exceder {LEGAL_NAME_MAX_LEN} caracteres"
    return None


def validate_customer(
    rfc: str,
    legal_name: str,
    zip_val: str = "",
    tax_system: str = "",
    email: Optional[str] = None,
) -> list[str]:
    """
    Valida datos de cliente. Retorna lista de mensajes de error (vacía si todo ok).
    """
    errors: list[str] = []
    err = validate_rfc(rfc)
    if err:
        errors.append(err)
    err = validate_legal_name(legal_name)
    if err:
        errors.append(err)
    err = validate_zip(zip_val or "")
    if err:
        errors.append(err)
    err = validate_tax_system(tax_system or "")
    if err:
        errors.append(err)
    err = validate_email(email)
    if err:
        errors.append(err)
    return errors


def validate_product_key(product_key: str) -> Optional[str]:
    """Clave producto/servicio SAT: 8 dígitos."""
    if not product_key or not product_key.strip():
        return "Clave ProdServ es obligatoria"
    key = product_key.strip()
    # Permitir formato "12345678" o "12345678 — Descripción" (se usa en UI)
    if "—" in key:
        key = key.split("—")[0].strip()
    if not _PRODUCT_KEY_PATTERN.match(key):
        return "Clave ProdServ debe ser un código de 8 dígitos del catálogo SAT"
    return None


def validate_unit_key(unit_key: str) -> Optional[str]:
    """Unidad SAT: 2 o 3 caracteres alfanuméricos (E48, H87, MTR, etc.)."""
    if not unit_key or not unit_key.strip():
        return None  # opcional, backend usa E48 por defecto
    u = unit_key.strip().upper()
    if not _UNIT_KEY_PATTERN.match(u):
        return "Unidad debe ser una clave SAT de 2 o 3 caracteres (ej. E48, H87)"
    return None


def validate_product_description(description: str) -> Optional[str]:
    """Descripción del producto: obligatoria y longitud máxima."""
    if not description or not description.strip():
        return "Descripción es obligatoria"
    if len(description.strip()) > DESCRIPTION_MAX_LEN:
        return f"Descripción no puede exceder {DESCRIPTION_MAX_LEN} caracteres"
    return None


def validate_product(
    description: str,
    product_key: str,
    unit_key: str = "",
    unit_price: Optional[float] = None,
) -> list[str]:
    """
    Valida datos de producto. Retorna lista de mensajes de error (vacía si todo ok).
    unit_price se valida en el endpoint (tipo y >= 0).
    """
    errors: list[str] = []
    err = validate_product_description(description)
    if err:
        errors.append(err)
    err = validate_product_key(product_key)
    if err:
        errors.append(err)
    err = validate_unit_key(unit_key or "")
    if err:
        errors.append(err)
    if unit_price is not None and unit_price < 0:
        errors.append("Precio unitario debe ser mayor o igual a 0")
    return errors
