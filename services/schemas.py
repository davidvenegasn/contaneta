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

from pydantic import BaseModel, Field, field_validator

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

    @field_validator("rfc")
    @classmethod
    def _norm_rfc(cls, v: str) -> str:
        v = (v or "").strip().upper()
        if not v:
            raise ValueError("RFC requerido")
        if len(v) < 12 or len(v) > 13 or not _RFC_RE.match(v):
            raise ValueError("RFC inválido")
        return v

    @field_validator("legal_name")
    @classmethod
    def _norm_legal_name(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("Razón social requerida")
        return v

    @field_validator("zip")
    @classmethod
    def _norm_zip(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        s = (str(v) or "").strip()
        if not s:
            return None
        if not re.fullmatch(r"\d{5}", s):
            raise ValueError("Código postal debe tener 5 dígitos")
        return s

    @field_validator("tax_system")
    @classmethod
    def _norm_tax_system(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        s = (v or "").strip().upper()
        return s or None

    @field_validator("alias")
    @classmethod
    def _norm_alias(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        s = (v or "").strip()
        return s or None

    @field_validator("email")
    @classmethod
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

    @field_validator("rfc")
    @classmethod
    def _u_rfc(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        s = (v or "").strip().upper()
        if not s:
            return None
        if len(s) < 12 or len(s) > 13 or not _RFC_RE.match(s):
            raise ValueError("RFC inválido")
        return s

    @field_validator("legal_name")
    @classmethod
    def _u_name(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        s = (v or "").strip()
        return s or None

    @field_validator("zip")
    @classmethod
    def _u_zip(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        s = (str(v) or "").strip()
        if not s:
            return None
        if not re.fullmatch(r"\d{5}", s):
            raise ValueError("Código postal debe tener 5 dígitos")
        return s

    @field_validator("tax_system")
    @classmethod
    def _u_tax(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        s = (v or "").strip().upper()
        return s or None

    @field_validator("email")
    @classmethod
    def _u_email(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        s = (v or "").strip()
        if not s:
            return None
        if not _EMAIL_RE.match(s):
            raise ValueError("Email inválido")
        return s

    @field_validator("alias")
    @classmethod
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

    @field_validator("description")
    @classmethod
    def _norm_desc(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("Descripción requerida")
        return v

    @field_validator("product_key")
    @classmethod
    def _norm_product_key(cls, v: str) -> str:
        v = (v or "").strip().upper()
        if not v:
            raise ValueError("Clave ProdServ requerida")
        if "—" in v:
            v = v.split("—", 1)[0].strip()
        return v

    @field_validator("unit_key")
    @classmethod
    def _norm_unit_key(cls, v: str) -> str:
        v = (v or "").strip().upper()
        return v or "E48"

    @field_validator("unit_price")
    @classmethod
    def _norm_unit_price(cls, v: float) -> float:
        if v is None:
            raise ValueError("Precio unitario requerido")
        if v < 0:
            raise ValueError("Precio unitario no puede ser negativo")
        return float(v)

    @field_validator("iva_rate", mode="before")
    @classmethod
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
            n = n / 100.0
        return max(0.0, min(1.0, n))


class ProductCreate(ProductBase):
    pass


class ProductUpdate(ProductBase):
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

    @field_validator("customer_zip")
    @classmethod
    def _norm_c_zip(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        s = (v or "").strip()
        if not s:
            return None
        if not re.fullmatch(r"\d{5}", s):
            raise ValueError("Código postal debe tener 5 dígitos")
        return s

    @field_validator("customer_tax_system")
    @classmethod
    def _norm_c_tax_system(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        s = (v or "").strip().upper()
        return s or None

    @field_validator("customer_email")
    @classmethod
    def _norm_c_email(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        s = (v or "").strip()
        if not s:
            return None
        if not _EMAIL_RE.match(s):
            raise ValueError("Email inválido")
        return s

    @field_validator("cfdi_use", "payment_form", "payment_method", "currency", mode="before")
    @classmethod
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

    @field_validator("alias")
    @classmethod
    def _norm_alias_b(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("Alias requerido")
        return v

    @field_validator("bank_name")
    @classmethod
    def _norm_bank_name(cls, v: str) -> str:
        s = (v or "").strip()
        return s or "Otro"

    @field_validator("clabe")
    @classmethod
    def _norm_clabe(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        s = (str(v) or "").strip()
        if not s:
            return None
        if not re.fullmatch(r"\d{18}", s):
            raise ValueError("La CLABE debe tener 18 dígitos")
        return s

    @field_validator("account_last4")
    @classmethod
    def _norm_last4(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        s = (str(v) or "").strip()
        if not s:
            return None
        return s[:4]

    @field_validator("rfc_titular")
    @classmethod
    def _norm_rfc_titular(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        s = (v or "").strip().upper()
        if not s:
            return None
        if len(s) < 12 or len(s) > 13 or not _RFC_RE.match(s):
            raise ValueError("RFC del titular inválido")
        return s


class BankAccountCreate(BankAccountBase):
    pass


class BankAccountUpdate(BankAccountBase):
    pass
