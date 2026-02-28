from __future__ import annotations

from typing import Any

from services import invoices_service


def normalize_invoice_input(*, customer: dict[str, Any], items: list[dict[str, Any]] | None) -> tuple[dict[str, Any], list[dict[str, Any]] | None]:
    """
    Normaliza input mínimo para facturación.
    MVP: solo asegura que customer tenga campos esperados y items sea lista (o None).
    """
    cust = customer or {}
    if not isinstance(cust, dict):
        cust = {}
    if items is not None and not isinstance(items, list):
        items = []
    return cust, items


def build_facturapi_payload(
    *,
    invoice_type: str,
    export_code: str = "01",
    customer: dict[str, Any],
    items: list[dict[str, Any]] | None,
    payments: list[dict[str, Any]] | None = None,
    cfdi_use: str = "G03",
    payment_form: str = "03",
    payment_method: str = "PUE",
    currency: str = "MXN",
    series: str | None = None,
    folio_number: int | None = None,
    issue_date: str | None = None,
    order_ref: str | None = None,
    notes: str | None = None,
    exchange: float | None = None,
) -> dict[str, Any]:
    cust_in, items_in = normalize_invoice_input(customer=customer, items=items)
    cust_payload = invoices_service.build_customer(
        rfc=str(cust_in.get("rfc") or cust_in.get("tax_id") or ""),
        legal_name=str(cust_in.get("legal_name") or ""),
        zip_code=str((cust_in.get("zip") or cust_in.get("zip_code") or cust_in.get("customer_zip") or "")),
        tax_system=str((cust_in.get("tax_system") or cust_in.get("customer_tax_system") or "")),
        email=(cust_in.get("email") or cust_in.get("customer_email") or None),
    )
    payload = invoices_service.build_invoice_payload(
        invoice_type=invoice_type,
        export_code=export_code,
        customer=cust_payload,
        items=items_in,
        payments=payments,
        cfdi_use=cfdi_use,
        payment_form=payment_form,
        payment_method=payment_method,
        currency=currency,
        series=series,
        folio_number=folio_number,
        issue_date=issue_date,
        order_ref=order_ref,
        notes=notes,
        exchange=exchange,
    )
    invoices_service.validate_invoice_payload(payload)
    return payload


def validate(payload: dict[str, Any]) -> None:
    invoices_service.validate_invoice_payload(payload)

