from __future__ import annotations

from typing import Any

from services.errors import ValidationError


def build_customer(
    *,
    rfc: str,
    legal_name: str,
    zip_code: str,
    tax_system: str,
    email: str | None = None,
    foreign_id: str | None = None,
    residence: str | None = None,
) -> dict[str, Any]:
    rfc_n = (rfc or "").strip().upper()
    name_n = (legal_name or "").strip()
    zip_n = (zip_code or "").strip()
    tax_n = (tax_system or "").strip()
    is_extranjero = rfc_n == "XEXX010101000"
    if not rfc_n:
        raise ValidationError(code="INV_CUSTOMER_RFC_REQUIRED", public_message="RFC requerido.")
    if not name_n:
        raise ValidationError(code="INV_CUSTOMER_NAME_REQUIRED", public_message="Razón social requerida.")
    if not zip_n and not is_extranjero:
        raise ValidationError(code="INV_CUSTOMER_ZIP_REQUIRED", public_message="Código postal requerido.")
    if not tax_n:
        raise ValidationError(code="INV_CUSTOMER_TAX_SYSTEM_REQUIRED", public_message="Régimen fiscal requerido.")
    if is_extranjero and not residence:
        raise ValidationError(
            code="INV_CUSTOMER_RESIDENCE_REQUIRED",
            public_message="País de residencia fiscal requerido para facturas al extranjero.",
        )
    email_n = (email or "").strip() or None
    payload: dict[str, Any] = {
        "legal_name": name_n,
        "email": email_n,
        "tax_id": rfc_n,
        "tax_system": tax_n,
        "address": {"zip": zip_n or "00000"},
    }
    if is_extranjero and residence:
        payload["residence_country_code"] = (residence or "").strip().upper()
    if is_extranjero and foreign_id:
        payload["foreign_tax_id"] = (foreign_id or "").strip()
    return payload


def build_invoice_payload(
    *,
    invoice_type: str,
    export_code: str,
    customer: dict[str, Any],
    items: list[dict[str, Any]] | None,
    payments: list[dict[str, Any]] | None = None,
    related_documents: list[dict[str, Any]] | None = None,
    cfdi_use: str,
    payment_form: str,
    payment_method: str,
    currency: str,
    series: str | None = None,
    folio_number: int | None = None,
    issue_date: str | None = None,
    order_ref: str | None = None,
    notes: str | None = None,
    exchange: float | None = None,
) -> dict[str, Any]:
    """
    Single source of truth para construir el payload que se manda a Facturapi.
    Nota: `items` debe estar en formato Facturapi (cada item con product/quantity/etc).
    """
    t = (invoice_type or "").strip().upper()
    if not t:
        raise ValidationError(code="INV_TYPE_REQUIRED", public_message="Tipo de comprobante requerido.")
    export_n = (export_code or "01").strip() or "01"
    cfdi_use_n = (cfdi_use or "G03").strip().upper() or "G03"
    payment_form_n = (payment_form or "03").strip() or "03"
    payment_method_n = (payment_method or "PUE").strip().upper() or "PUE"
    currency_n = (currency or "MXN").strip().upper() or "MXN"

    payload: dict[str, Any] = {
        "type": t,
        "export": export_n,
        "customer": customer,
        "use": cfdi_use_n,
        "payment_form": payment_form_n,
        "payment_method": payment_method_n,
        "currency": currency_n,
    }
    if items is not None:
        payload["items"] = items
    if payments is not None:
        payload["payments"] = payments
    if related_documents:
        payload["related_documents"] = related_documents
    if series:
        payload["series"] = series
    if folio_number is not None:
        payload["folio_number"] = folio_number
    if issue_date:
        payload["date"] = issue_date
    if order_ref:
        payload["external_id"] = order_ref
    if notes:
        payload["conditions"] = notes
    if exchange is not None:
        payload["exchange"] = exchange
    return payload


def validate_invoice_payload(payload: dict[str, Any]) -> None:
    if not isinstance(payload, dict):
        raise ValidationError(code="INV_PAYLOAD_INVALID", public_message="Payload inválido.")
    for key in ("type", "export", "customer", "use", "payment_form", "payment_method", "currency"):
        if key not in payload:
            raise ValidationError(code="INV_PAYLOAD_MISSING", public_message="Payload incompleto.")
    cust = payload.get("customer") or {}
    if not isinstance(cust, dict) or not cust.get("tax_id"):
        raise ValidationError(code="INV_PAYLOAD_CUSTOMER", public_message="Cliente inválido.")

