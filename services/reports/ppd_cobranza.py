"""PPD outstanding balance (cobranza) report builder."""
import logging
from datetime import datetime

from database import db_rows

logger = logging.getLogger(__name__)


def build_ppd_outstanding_report(issuer_id: int) -> dict:
    """Build a report of PPD invoices with outstanding balances.

    Returns:
        Dict with total_pendiente, count, items (sorted by days_since_emission DESC).
    """
    # Get all PPD invoices that aren't fully cancelled
    invoices = db_rows(
        """SELECT i.id, i.uuid, i.total, i.currency, i.customer_rfc,
                  i.customer_legal_name, i.created_at,
                  s.fecha_emision
             FROM invoices i
             LEFT JOIN sat_cfdi s ON LOWER(TRIM(s.uuid)) = LOWER(TRIM(i.uuid))
                  AND s.issuer_id = i.issuer_id AND s.direction = 'issued'
            WHERE i.issuer_id = ? AND i.payment_method = 'PPD'
              AND i.cancelled = 0
            ORDER BY COALESCE(s.fecha_emision, i.created_at) ASC""",
        (issuer_id,),
    )

    now = datetime.now()
    items = []
    total_pendiente = 0.0

    for inv in invoices:
        inv = dict(inv)
        invoice_id = inv["id"]
        total = float(inv.get("total") or 0)

        # Get payments for this invoice
        payments = db_rows(
            """SELECT parcialidad, saldo_insoluto
                 FROM invoice_payments
                WHERE invoice_id = ? AND issuer_id = ?
                ORDER BY parcialidad DESC LIMIT 1""",
            (invoice_id, issuer_id),
        )

        if payments:
            saldo = float(payments[0].get("saldo_insoluto", 0))
            parcialidades = payments[0].get("parcialidad", 0)
        else:
            saldo = total
            parcialidades = 0

        if saldo <= 0:
            continue

        fecha_str = inv.get("fecha_emision") or inv.get("created_at") or ""
        days = 0
        if fecha_str:
            try:
                dt = datetime.fromisoformat(fecha_str[:10])
                days = (now - dt).days
            except Exception:
                pass

        items.append({
            "uuid": inv.get("uuid"),
            "customer_rfc": inv.get("customer_rfc"),
            "customer_name": inv.get("customer_legal_name"),
            "total_original": total,
            "saldo_insoluto": saldo,
            "currency": inv.get("currency") or "MXN",
            "parcialidades_pagadas": parcialidades,
            "dias_desde_emision": days,
            "fecha_emision": fecha_str[:10] if fecha_str else "",
        })
        total_pendiente += saldo

    items.sort(key=lambda x: x["dias_desde_emision"], reverse=True)

    return {
        "total_pendiente": round(total_pendiente, 2),
        "count": len(items),
        "invoices": items,
    }
