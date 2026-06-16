"""
Unified invoice engine — single source of truth for invoice creation.

Consolidates:
- Receiver validation (CFDI 4.0)
- Tax computation (IVA, ISR retention)
- Catalog defaults
- Facturapi payload building

Used by: quick invoice, full invoice form, product-based invoice, client-based invoice.
"""
from __future__ import annotations

import re
from typing import Any

from database import safe_update
from services.errors import ValidationError
from services.invoices import invoices_service

# ---------- CFDI 4.0 defaults ----------

DEFAULT_CFDI_USE = "G03"  # Gastos en general
DEFAULT_PAYMENT_FORM = "03"  # Transferencia electrónica
DEFAULT_PAYMENT_METHOD = "PUE"  # Pago en una sola exhibición
DEFAULT_CURRENCY = "MXN"
DEFAULT_EXPORT = "01"  # No aplica
DEFAULT_IVA_RATE = 0.16

# RFC validation patterns
_RFC_PF_RE = re.compile(r"^[A-Z&Ñ]{4}\d{6}[A-Z0-9]{3}$")  # Persona Física (13 chars)
_RFC_PM_RE = re.compile(r"^[A-Z&Ñ]{3}\d{6}[A-Z0-9]{3}$")  # Persona Moral (12 chars)
_RFC_GENERIC = "XAXX010101000"  # Público en general
_RFC_EXTRANJERO = "XEXX010101000"  # Extranjero

# UsoCFDI codes allowed only for personas físicas (régimen personal).
# Using one of these with a persona moral (e.g. 601) triggers CFDI40173.
_CFDI_USE_PF_ONLY = {
    "D01", "D02", "D03", "D04", "D05", "D06", "D07", "D08", "D09", "D10",
}
# Régimen codes for personas morales
_REGIMEN_PM = {"601", "603", "607", "608", "609", "620", "623", "624", "628", "630"}


def validate_uso_cfdi_regimen(cfdi_use: str, tax_system: str) -> str | None:
    """Return an error message if the UsoCFDI/régimen combo is invalid, else None."""
    use = (cfdi_use or "").strip().upper()
    ts = (tax_system or "").strip()
    if use in _CFDI_USE_PF_ONLY and ts in _REGIMEN_PM:
        return (
            f"El uso de CFDI '{use}' es solo para personas físicas. "
            f"Para el régimen {ts} (persona moral) usa G03 o S01."
        )
    return None


# ---------- Receiver (customer) validation ----------

def validate_receiver_cfdi40(
    *,
    rfc: str,
    legal_name: str,
    zip_code: str,
    tax_system: str,
    cfdi_use: str = DEFAULT_CFDI_USE,
) -> list[str]:
    """
    Validate receiver fields per CFDI 4.0 rules.
    Returns list of error messages (empty = valid).
    """
    errors: list[str] = []
    rfc_n = (rfc or "").strip().upper()
    if not rfc_n:
        errors.append("RFC del receptor es requerido.")
    elif rfc_n not in (_RFC_GENERIC, _RFC_EXTRANJERO):
        if not _RFC_PF_RE.match(rfc_n) and not _RFC_PM_RE.match(rfc_n):
            errors.append(f"RFC '{rfc_n}' no tiene formato válido (12 o 13 caracteres alfanuméricos).")

    if not (legal_name or "").strip():
        errors.append("Razón social / nombre del receptor es requerido.")

    zip_n = (zip_code or "").strip()
    if not zip_n:
        errors.append("Código postal del receptor es requerido.")
    elif not re.match(r"^\d{5}$", zip_n):
        errors.append(f"Código postal '{zip_n}' debe ser de 5 dígitos.")

    tax_n = (tax_system or "").strip()
    if not tax_n:
        errors.append("Régimen fiscal del receptor es requerido.")
    elif not re.match(r"^\d{3}$", tax_n):
        errors.append(f"Régimen fiscal '{tax_n}' debe ser un código de 3 dígitos (ej. 601, 612, 626).")

    cfdi_use_n = (cfdi_use or "").strip().upper()
    if cfdi_use_n and not re.match(r"^[A-Z]\d{2}$", cfdi_use_n):
        errors.append(f"Uso de CFDI '{cfdi_use_n}' no tiene formato válido.")

    return errors


# ---------- Tax computation ----------

def compute_line_taxes(
    *,
    unit_price: float,
    quantity: float = 1,
    iva_rate: float = DEFAULT_IVA_RATE,
    isr_retention_rate: float = 0.0,
    iva_retention_rate: float = 0.0,
    discount: float = 0.0,
) -> dict[str, Any]:
    """
    Compute taxes for a single invoice line.
    Returns: { subtotal, iva, isr_retention, iva_retention, total, taxes[] }
    """
    subtotal = round(unit_price * quantity, 2)
    if discount > 0:
        subtotal = round(subtotal - discount, 2)

    iva = round(subtotal * iva_rate, 2) if iva_rate > 0 else 0.0
    isr_ret = round(subtotal * isr_retention_rate, 2) if isr_retention_rate > 0 else 0.0
    iva_ret = round(subtotal * iva_retention_rate, 2) if iva_retention_rate > 0 else 0.0
    total = round(subtotal + iva - isr_ret - iva_ret, 2)

    taxes = []
    if iva_rate > 0:
        taxes.append({
            "type": "IVA",
            "rate": iva_rate,
            "factor": "Tasa",
            "base": subtotal,
            "amount": iva,
            "withholding": False,
        })
    if isr_retention_rate > 0:
        taxes.append({
            "type": "ISR",
            "rate": isr_retention_rate,
            "factor": "Tasa",
            "base": subtotal,
            "amount": isr_ret,
            "withholding": True,
        })
    if iva_retention_rate > 0:
        taxes.append({
            "type": "IVA",
            "rate": iva_retention_rate,
            "factor": "Tasa",
            "base": subtotal,
            "amount": iva_ret,
            "withholding": True,
        })

    return {
        "subtotal": subtotal,
        "iva": iva,
        "isr_retention": isr_ret,
        "iva_retention": iva_ret,
        "total": total,
        "taxes": taxes,
    }


def compute_invoice_totals(items: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Compute totals for an entire invoice from line items.
    Each item should have: unit_price, quantity, iva_rate (optional).
    Returns: { subtotal, total_iva, total_retentions, total }
    """
    subtotal = 0.0
    total_iva = 0.0
    total_ret = 0.0

    for item in items:
        price = float(item.get("unit_price") or item.get("price") or 0)
        qty = float(item.get("quantity") or 1)
        iva_rate = float(item.get("iva_rate") if item.get("iva_rate") is not None else DEFAULT_IVA_RATE)
        discount = float(item.get("discount") or 0)

        line = compute_line_taxes(
            unit_price=price,
            quantity=qty,
            iva_rate=iva_rate,
            discount=discount,
        )
        subtotal += line["subtotal"]
        total_iva += line["iva"]
        total_ret += line["isr_retention"] + line["iva_retention"]

    total = round(subtotal + total_iva - total_ret, 2)
    return {
        "subtotal": round(subtotal, 2),
        "total_iva": round(total_iva, 2),
        "total_retentions": round(total_ret, 2),
        "total": total,
    }


# ---------- Catalog defaults ----------

def load_catalog_defaults() -> dict[str, Any]:
    """Load default catalog values for invoice creation forms."""
    return {
        "cfdi_use": DEFAULT_CFDI_USE,
        "payment_form": DEFAULT_PAYMENT_FORM,
        "payment_method": DEFAULT_PAYMENT_METHOD,
        "currency": DEFAULT_CURRENCY,
        "export": DEFAULT_EXPORT,
        "iva_rate": DEFAULT_IVA_RATE,
    }


# ---------- Input normalization ----------

def normalize_invoice_input(
    *, customer: dict[str, Any], items: list[dict[str, Any]] | None
) -> tuple[dict[str, Any], list[dict[str, Any]] | None]:
    """Normalize minimal input for invoicing."""
    cust = customer or {}
    if not isinstance(cust, dict):
        cust = {}
    if items is not None and not isinstance(items, list):
        items = []
    return cust, items


# ---------- Main builder ----------

def build_facturapi_payload(
    *,
    invoice_type: str,
    export_code: str = DEFAULT_EXPORT,
    customer: dict[str, Any],
    items: list[dict[str, Any]] | None,
    payments: list[dict[str, Any]] | None = None,
    related_documents: list[dict[str, Any]] | None = None,
    cfdi_use: str = DEFAULT_CFDI_USE,
    payment_form: str = DEFAULT_PAYMENT_FORM,
    payment_method: str = DEFAULT_PAYMENT_METHOD,
    currency: str = DEFAULT_CURRENCY,
    series: str | None = None,
    folio_number: int | None = None,
    issue_date: str | None = None,
    order_ref: str | None = None,
    notes: str | None = None,
    exchange: float | None = None,
    validate_receiver: bool = True,
) -> dict[str, Any]:
    """
    Build a complete Facturapi payload with validation.
    Single entry point for all invoice creation paths.
    """
    cust_in, items_in = normalize_invoice_input(customer=customer, items=items)

    # Extract customer fields with flexible key names
    rfc = str(cust_in.get("rfc") or cust_in.get("tax_id") or "")
    legal_name = str(cust_in.get("legal_name") or "")
    zip_code = str(cust_in.get("zip") or cust_in.get("zip_code") or cust_in.get("customer_zip") or "")
    tax_system = str(cust_in.get("tax_system") or cust_in.get("customer_tax_system") or "")
    email = cust_in.get("email") or cust_in.get("customer_email") or None
    foreign_id = cust_in.get("foreign_id") or cust_in.get("foreign_tax_id") or None
    residence = cust_in.get("residence") or cust_in.get("residence_country_code") or None

    # Validate receiver if requested
    if validate_receiver:
        errors = validate_receiver_cfdi40(
            rfc=rfc,
            legal_name=legal_name,
            zip_code=zip_code,
            tax_system=tax_system,
            cfdi_use=cfdi_use,
        )
        if errors:
            raise ValidationError(
                code="INV_RECEIVER_INVALID",
                public_message=" | ".join(errors),
            )
        # UsoCFDI × régimen cross-validation (CFDI40173)
        use_err = validate_uso_cfdi_regimen(cfdi_use, tax_system)
        if use_err:
            raise ValidationError(code="INV_CFDI_USE_REGIMEN", public_message=use_err)

    cust_payload = invoices_service.build_customer(
        rfc=rfc,
        legal_name=legal_name,
        zip_code=zip_code,
        tax_system=tax_system,
        email=email,
        foreign_id=foreign_id or None,
        residence=residence or None,
    )

    payload = invoices_service.build_invoice_payload(
        invoice_type=invoice_type,
        export_code=export_code,
        customer=cust_payload,
        items=items_in,
        payments=payments,
        related_documents=related_documents,
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
    """Validate an already-built payload."""
    invoices_service.validate_invoice_payload(payload)


# ---------- DB persistence ----------

def save_invoice_record(
    conn,
    issuer_id: int,
    *,
    currency: str,
    exchange_rate: float | None,
    payment_form: str,
    payment_method: str,
    cfdi_use: str,
    customer_rfc: str,
    customer_legal_name: str,
    customer_zip: str,
    customer_tax_system: str,
    customer_email: str | None,
    export_code: str = "01",
    tipo_comprobante: str = "I",
    series: str | None = None,
    folio_number: int | None = None,
    order_ref: str | None = None,
    issue_date: str | None = None,
    notes: str | None = None,
) -> int:
    """Insert invoice header row + optional columns. Returns invoice_local_id."""
    cur = conn.execute(
        """
        INSERT INTO invoices (
            issuer_id, currency, exchange_rate,
            payment_form, payment_method, cfdi_use,
            customer_rfc, customer_legal_name,
            customer_zip, customer_tax_system, customer_email
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            issuer_id, currency, exchange_rate,
            payment_form, payment_method, cfdi_use,
            customer_rfc, customer_legal_name,
            customer_zip, customer_tax_system, customer_email,
        ),
    )
    invoice_local_id = cur.lastrowid
    safe_update(
        conn, "invoices", invoice_local_id,
        {
            "export_code": export_code,
            "tipo_comprobante": tipo_comprobante,
            "series": series,
            "folio_number": folio_number,
            "order_ref": order_ref,
            "issue_date": issue_date,
            "notes": notes,
        },
    )
    return invoice_local_id


def save_invoice_items(conn, invoice_local_id: int, items: list[dict[str, Any]]) -> None:
    """Persist Facturapi-format line items into invoice_items table."""
    if not items:
        return
    pragma_rows = conn.execute("PRAGMA table_info(invoice_items)").fetchall()
    cols = set()
    for r in pragma_rows:
        name = r.get("name")
        if name:
            cols.add(name)
    base_cols = ["invoice_id", "quantity", "description", "product_key", "unit_price", "iva_rate"]
    has_unit_key = "unit_key" in cols
    has_discount = "discount" in cols
    insert_cols = base_cols + (["unit_key"] if has_unit_key else []) + (["discount"] if has_discount else [])
    placeholders = ", ".join(["?"] * len(insert_cols))
    col_sql = ", ".join(insert_cols)
    for it in items:
        base_vals = [
            invoice_local_id,
            it["quantity"],
            it["product"]["description"],
            it["product"]["product_key"],
            it["product"]["price"],
            it["product"]["taxes"][0]["rate"] if it["product"].get("taxes") else 0.16,
        ]
        extra_vals: list = []
        if has_unit_key:
            extra_vals.append(it["product"].get("unit_key"))
        if has_discount:
            extra_vals.append(it.get("discount", 0.0))
        conn.execute(
            f"INSERT INTO invoice_items ({col_sql}) VALUES ({placeholders})",
            tuple(base_vals + extra_vals),
        )


def update_invoice_stamp(
    conn,
    invoice_local_id: int,
    issuer_id: int,
    *,
    facturapi_id: str | None,
    uuid: str | None,
    total: float | None,
) -> None:
    """Stamp result: set facturapi_invoice_id, uuid, total on the invoice row."""
    conn.execute(
        "UPDATE invoices SET facturapi_invoice_id = ?, uuid = ?, total = ? WHERE id = ? AND issuer_id = ?",
        (facturapi_id, uuid, total, invoice_local_id, issuer_id),
    )
    conn.commit()


def mirror_emitted_to_sat_cfdi(
    conn,
    issuer_id: int,
    *,
    uuid: str,
    issuer_rfc: str,
    issuer_legal_name: str,
    customer_rfc: str,
    customer_legal_name: str,
    total: float | None,
    currency: str,
    tipo_comprobante: str,
    series: str | None,
    folio_number: int | None,
    payment_form: str | None,
    payment_method: str | None,
    cfdi_use: str | None,
    issue_date: str | None,
) -> None:
    """Insert a row into sat_cfdi for a freshly-emitted CFDI so it shows up
    immediately in the portal's "Emitidas" listing — without waiting for the
    next SAT sync (which is the slow cron-driven path that populates the rest
    of the data later).

    INSERT OR IGNORE on uuid so:
      - If the SAT sync already ran, we don't overwrite its richer data.
      - If our mirror ran first, the sync can later UPDATE us if needed.
    """
    if not uuid:
        return
    try:
        conn.execute(
            """INSERT OR IGNORE INTO sat_cfdi (
                issuer_id, direction, uuid, status, fecha_emision,
                rfc_emisor, nombre_emisor, rfc_receptor, nombre_receptor,
                total, moneda, tipo_comprobante,
                serie, folio, forma_pago, metodo_pago, uso_cfdi,
                created_at, updated_at
            ) VALUES (
                ?, 'issued', UPPER(TRIM(?)), '1', COALESCE(?, datetime('now')),
                ?, ?, ?, ?,
                ?, ?, ?,
                ?, ?, ?, ?, ?,
                datetime('now'), datetime('now')
            )""",
            (
                int(issuer_id),
                uuid,
                issue_date,
                (issuer_rfc or "").upper(),
                issuer_legal_name or "",
                (customer_rfc or "").upper(),
                customer_legal_name or "",
                float(total) if total is not None else None,
                (currency or "MXN").upper(),
                tipo_comprobante or "I",
                series or None,
                str(folio_number) if folio_number is not None else None,
                payment_form or None,
                payment_method or None,
                cfdi_use or None,
            ),
        )
        conn.commit()
    except Exception:
        # Best-effort mirror — never block the emission flow if this fails.
        logger.exception("mirror_emitted_to_sat_cfdi failed for uuid=%s", uuid[:36])
