"""
Esquemas Pydantic para validar payloads de APIs (clientes, productos, facturas rápidas, banco).

Objetivo:
- Normalizar strings (strip / mayúsculas donde aplica).
- Validar formatos básicos (RFC, CP, email).
- Evitar que inputs inválidos lleguen a la lógica/SQL.
"""

from __future__ import annotations

import re
from typing import Optional

from pydantic import BaseModel, Field, validator

_RFC_RE = re.compile(r"^[A-ZÑ&]{3,4}[0-9]{6}[A-Z0-9]{2,3}$")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class PaginationParams(BaseModel):
    limit: int = Field(200, ge=1, le=500)
    offset: int = Field(0, ge=0)


class ClientBase(BaseModel):
    rfc: str = Field(..., description="RFC del cliente")
    legal_name: str = Field(..., description="Razón social o nombre")
    zip: Optional[str] = Field(None, description="Código postal (5 dígitos)")
    tax_system: Optional[str] = Field(None, description="Régimen fiscal SAT (código)")
    email: Optional[str] = Field(None, description="Email de contacto")
    alias: Optional[str] = Field(None, description="Alias interno")

    @validator("rfc")
    def _norm_rfc(cls, v: str) -> str:
        v = (v or "").strip().upper()
        if not v:
            raise ValueError("RFC requerido")
        if len(v) < 12 or len(v) > 13 or not _RFC_RE.match(v):
            # Validador laxo: no bloquear RFCs especiales, pero evitar basura evidente
            raise ValueError("RFC inválido")
        return v

    @validator("legal_name")
    def _norm_legal_name(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("Razón social requerida")
        return v

    @validator("zip")
    def _norm_zip(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        s = (str(v) or "").strip()
        if not s:
            return None
        if not re.fullmatch(r"\d{5}", s):
            raise ValueError("Código postal debe tener 5 dígitos")
        return s

    @validator("tax_system")
    def _norm_tax_system(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        s = (v or "").strip().upper()
        return s or None

    @validator("alias")
    def _norm_alias(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        s = (v or "").strip()
        return s or None

    @validator("email")
    def _norm_email(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        s = (v or "").strip()
        if not s:
            return None
        if not _EMAIL_RE.match(s):
            raise ValueError("Email inválido")
        return s


class ClientCreate(ClientBase):
    pass


class ClientUpdate(BaseModel):
    """Update parcial (todos opcionales)."""
    rfc: Optional[str] = None
    legal_name: Optional[str] = None
    zip: Optional[str] = None
    tax_system: Optional[str] = None
    email: Optional[str] = None
    alias: Optional[str] = None

    @validator("rfc")
    def _u_rfc(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        s = (v or "").strip().upper()
        if not s:
            return None
        if len(s) < 12 or len(s) > 13 or not _RFC_RE.match(s):
            raise ValueError("RFC inválido")
        return s

    @validator("legal_name")
    def _u_name(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        s = (v or "").strip()
        return s or None

    @validator("zip")
    def _u_zip(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        s = (str(v) or "").strip()
        if not s:
            return None
        if not re.fullmatch(r"\d{5}", s):
            raise ValueError("Código postal debe tener 5 dígitos")
        return s

    @validator("tax_system")
    def _u_tax(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        s = (v or "").strip().upper()
        return s or None

    @validator("email")
    def _u_email(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        s = (v or "").strip()
        if not s:
            return None
        if not _EMAIL_RE.match(s):
            raise ValueError("Email inválido")
        return s

    @validator("alias")
    def _u_alias(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        s = (v or "").strip()
        return s or None


class ProductBase(BaseModel):
    description: str = Field(..., description="Descripción del producto/servicio")
    product_key: str = Field(..., description="Clave ProdServ SAT")
    unit_key: str = Field("E48", description="Clave Unidad SAT")
    unit_price: float = Field(..., ge=0.0, description="Precio unitario (sin IVA)")
    iva_rate: float = Field(0.16, ge=0.0, le=1.0, description="Tasa de IVA (0–1)")

    @validator("description")
    def _norm_desc(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("Descripción requerida")
        return v

    @validator("product_key")
    def _norm_product_key(cls, v: str) -> str:
        v = (v or "").strip().upper()
        if not v:
            raise ValueError("Clave ProdServ requerida")
        # Si viene con descripción tipo "01010101 — Servicios", quedarnos con la clave antes del guión largo.
        if "—" in v:
            v = v.split("—", 1)[0].strip()
        return v

    @validator("unit_key")
    def _norm_unit_key(cls, v: str) -> str:
        v = (v or "").strip().upper()
        return v or "E48"

    @validator("unit_price")
    def _norm_unit_price(cls, v: float) -> float:
        if v is None:
            raise ValueError("Precio unitario requerido")
        if v < 0:
            raise ValueError("Precio unitario no puede ser negativo")
        return float(v)

    @validator("iva_rate", pre=True)
    def _norm_iva_rate(cls, v) -> float:
        if v is None or v == "":
            return 0.16
        s = str(v).strip().upper()
        if s == "EXENTO":
            return 0.0
        try:
            n = float(s)
        except (TypeError, ValueError):
            raise ValueError("Tasa de IVA inválida")
        if n < 0 or n > 1:
            # Permitir 0–100 y convertir a 0–1
            n = n / 100.0
        return max(0.0, min(1.0, n))


class ProductCreate(ProductBase):
    pass


class ProductUpdate(ProductBase):
    # En esta app, update suele ser full-replace; si en el futuro es parcial, se puede hacer opcional.
    pass


class QuickInvoiceIssueRequest(BaseModel):
    customer_id: int = Field(..., ge=1)
    product_id: int = Field(..., ge=1)
    quantity: float = Field(1.0, gt=0.0, le=999999)
    unit_price: Optional[float] = Field(None, ge=0.0)
    iva_rate: Optional[float] = Field(None, ge=0.0, le=1.0)
    iva_exempt: bool = False

    customer_legal_name: Optional[str] = None
    customer_zip: Optional[str] = None
    customer_tax_system: Optional[str] = None
    customer_email: Optional[str] = None

    description: Optional[str] = None
    product_key: Optional[str] = None
    unit_key: Optional[str] = None

    isr_ret_rate: Optional[float] = Field(0.0, ge=0.0, le=1.0)
    iva_ret_rate: Optional[float] = Field(0.0, ge=0.0, le=1.0)

    cfdi_use: str = Field("G03")
    payment_form: str = Field("03")
    payment_method: str = Field("PUE")
    currency: str = Field("MXN")
    send_email: bool = False

    @validator("customer_zip")
    def _norm_c_zip(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        s = (v or "").strip()
        if not s:
            return None
        if not re.fullmatch(r"\d{5}", s):
            raise ValueError("Código postal debe tener 5 dígitos")
        return s

    @validator("customer_tax_system")
    def _norm_c_tax_system(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        s = (v or "").strip().upper()
        return s or None

    @validator("customer_email")
    def _norm_c_email(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        s = (v or "").strip()
        if not s:
            return None
        if not _EMAIL_RE.match(s):
            raise ValueError("Email inválido")
        return s

    @validator("cfdi_use", "payment_form", "payment_method", "currency", pre=True)
    def _norm_sat_codes(cls, v: str) -> str:
        s = (v or "").strip().upper()
        return s or None


class BankAccountBase(BaseModel):
    alias: str = Field(..., description="Alias para mostrar en la UI")
    bank_name: str = Field(..., description="Nombre del banco")
    clabe: Optional[str] = Field(None, description="CLABE de 18 dígitos")
    account_last4: Optional[str] = Field(None, description="Últimos 4 dígitos de la cuenta")
    holder_name: Optional[str] = Field(None, description="Nombre del titular")
    rfc_titular: Optional[str] = Field(None, description="RFC del titular (opcional)")
    is_active: bool = True

    @validator("alias")
    def _norm_alias_b(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("Alias requerido")
        return v

    @validator("bank_name")
    def _norm_bank_name(cls, v: str) -> str:
        s = (v or "").strip()
        return s or "Otro"

    @validator("clabe")
    def _norm_clabe(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        s = (str(v) or "").strip()
        if not s:
            return None
        if not re.fullmatch(r"\d{18}", s):
            raise ValueError("La CLABE debe tener 18 dígitos")
        return s

    @validator("account_last4")
    def _norm_last4(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        s = (str(v) or "").strip()
        if not s:
            return None
        return s[:4]

    @validator("rfc_titular")
    def _norm_rfc_titular(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        s = (v or "").strip().upper()
        if not s:
            return None
        # Validador RFC laxo (mismo patrón que cliente)
        if len(s) < 12 or len(s) > 13 or not _RFC_RE.match(s):
            raise ValueError("RFC del titular inválido")
        return s


class BankAccountCreate(BankAccountBase):
    pass


class BankAccountUpdate(BankAccountBase):
    # En update todos los campos pueden ser opcionales, pero para simplificar lo mantenemos completo.
    pass

