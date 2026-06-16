"""REP (Recibo Electrónico de Pago) — Complemento de Pago 2.0 builder.

Computes NumParcialidad, ImpSaldoAnt, ImpSaldoInsoluto, EquivalenciaDR,
and proportional tax replication for a CFDI tipo P payload sent to Facturapi.
"""
from __future__ import annotations

import logging
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from database import db, db_rows
from services.errors import ValidationError

logger = logging.getLogger(__name__)

_TWO = Decimal("0.01")
_TEN = Decimal("0.0000000001")  # 10-decimal precision for EquivalenciaDR


def get_ppd_state(issuer_id: int, invoice_id: int) -> dict:
    """Return current PPD payment state for a given invoice.

    Returns:
        {invoice_id, total, moneda, saldo_insoluto, next_parcialidad,
         payments: [...]}
    """
    conn = db()
    try:
        inv = conn.execute(
            "SELECT id, total, currency, payment_method FROM invoices WHERE id = ? AND issuer_id = ?",
            (invoice_id, issuer_id),
        ).fetchone()
        if not inv:
            raise ValidationError(code="REP_INVOICE_NOT_FOUND", public_message="Factura no encontrada.")
        if inv["payment_method"] != "PPD":
            raise ValidationError(
                code="REP_NOT_PPD",
                public_message="Solo se puede emitir complemento de pago para facturas con método PPD.",
            )
        payments = db_rows(
            "SELECT * FROM invoice_payments WHERE invoice_id = ? ORDER BY parcialidad ASC",
            (invoice_id,),
        )
        total = Decimal(str(inv["total"] or 0))
        if payments:
            saldo = Decimal(str(payments[-1]["saldo_insoluto"]))
            next_parcialidad = payments[-1]["parcialidad"] + 1
        else:
            saldo = total
            next_parcialidad = 1
        return {
            "invoice_id": invoice_id,
            "total": float(total),
            "moneda": inv["currency"] or "MXN",
            "saldo_insoluto": float(saldo),
            "next_parcialidad": next_parcialidad,
            "payments": [dict(p) for p in payments],
        }
    finally:
        conn.close()


def compute_equivalencia_dr(
    saldo_anterior_mxn_equiv: Decimal,
    monto_pagado_moneda_pago: Decimal,
) -> Decimal:
    """Compute EquivalenciaDR = saldo_anterior (in MonedaDR) ÷ equivalent in MonedaP.

    Used when MonedaDR ≠ MonedaP (e.g. USD invoice paid in MXN).
    When same currency, EquivalenciaDR = 1.
    """
    if monto_pagado_moneda_pago == 0:
        return Decimal("1")
    result = saldo_anterior_mxn_equiv / monto_pagado_moneda_pago
    return result.quantize(_TEN, rounding=ROUND_HALF_UP)


def build_rep_payload(
    *,
    invoice: dict,
    fecha_pago: str,
    forma_pago: str,
    moneda_pago: str,
    tipo_cambio_pago: str | None,
    monto_pagado: float,
    importe_abonado: float,
    saldo_anterior: float,
    num_operacion: str | None,
    parcialidad: int,
) -> dict[str, Any]:
    """Build the Facturapi CFDI tipo P payload for a single payment.

    Args:
        invoice: row from invoices table (needs id, uuid, total, currency, customer_*)
        fecha_pago: ISO date YYYY-MM-DD of when payment was received
        forma_pago: SAT payment form code (03=SPEI, 02=cheque, 04=tarjeta…)
        moneda_pago: currency of the payment (MXN, USD…)
        tipo_cambio_pago: exchange rate if moneda_pago ≠ MXN (as string for precision)
        monto_pagado: total amount received in moneda_pago
        importe_abonado: amount credited to THIS invoice in MonedaDR
        saldo_anterior: outstanding balance before this payment in MonedaDR
        num_operacion: bank reference / transfer folio (optional)
        parcialidad: sequential payment number (1, 2, 3…)

    Returns:
        Facturapi payload dict for type P invoice.
    """
    moneda_dr = (invoice.get("currency") or "MXN").upper()
    moneda_pago_n = (moneda_pago or "MXN").upper()

    saldo_ant = Decimal(str(saldo_anterior))
    imp_abonado = Decimal(str(importe_abonado))
    saldo_insoluto = (saldo_ant - imp_abonado).quantize(_TWO, rounding=ROUND_HALF_UP)
    if saldo_insoluto < 0:
        saldo_insoluto = Decimal("0")

    # EquivalenciaDR: 1 when same currency, computed otherwise
    if moneda_dr == moneda_pago_n:
        equivalencia_dr = Decimal("1")
    else:
        equivalencia_dr = compute_equivalencia_dr(
            saldo_ant,
            Decimal(str(monto_pagado)),
        )

    related_doc: dict[str, Any] = {
        "uuid": invoice["uuid"],
        "currency": moneda_dr,
        "exchange_rate": float(equivalencia_dr),
        "installment": parcialidad,
        "previous_balance": float(saldo_ant),
        "amount": float(imp_abonado),
    }

    payment: dict[str, Any] = {
        "form": forma_pago,
        "currency": moneda_pago_n,
        "amount": float(Decimal(str(monto_pagado)).quantize(_TWO, rounding=ROUND_HALF_UP)),
        "date": fecha_pago,
        "related_documents": [related_doc],
    }
    if moneda_pago_n != "MXN" and tipo_cambio_pago:
        payment["exchange"] = float(Decimal(str(tipo_cambio_pago)))
    if num_operacion:
        payment["operation_number"] = num_operacion

    # Facturapi expects the customer from the original invoice
    customer = {
        "tax_id": invoice.get("customer_rfc", ""),
        "legal_name": invoice.get("customer_legal_name", ""),
        "tax_system": invoice.get("customer_tax_system", ""),
        "address": {"zip": invoice.get("customer_zip", "00000")},
    }

    return {
        "type": "P",
        "customer": customer,
        "payments": [payment],
    }


def record_payment(
    conn,
    *,
    issuer_id: int,
    invoice_id: int,
    rep_invoice_id: int | None,
    rep_uuid: str | None,
    parcialidad: int,
    fecha_pago: str,
    forma_pago: str,
    moneda_pago: str,
    tipo_cambio_pago: str | None,
    monto_pagado: float,
    importe_abonado: float,
    saldo_anterior: float,
    saldo_insoluto: float,
    num_operacion: str | None,
) -> int:
    """Insert a row into invoice_payments and return its id."""
    cur = conn.execute(
        """
        INSERT INTO invoice_payments (
            issuer_id, invoice_id, rep_invoice_id, rep_uuid,
            parcialidad, fecha_pago, forma_pago,
            moneda_pago, tipo_cambio_pago, monto_pagado,
            importe_abonado, saldo_anterior, saldo_insoluto, num_operacion
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            issuer_id, invoice_id, rep_invoice_id, rep_uuid,
            parcialidad, fecha_pago, forma_pago,
            moneda_pago, tipo_cambio_pago, monto_pagado,
            importe_abonado, saldo_anterior, saldo_insoluto, num_operacion,
        ),
    )
    return cur.lastrowid
