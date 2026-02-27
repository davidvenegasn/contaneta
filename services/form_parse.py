"""Parseo de formularios de factura (conceptos y pagos CFDI P)."""
import re
from typing import List


def parse_items_from_form(form) -> List[dict]:
    items: List[dict] = []
    idxs = set()
    for k in form.keys():
        m = re.match(r"^(qty|desc|key|price|iva|disc|unit)_(\d+)$", str(k))
        if m:
            idxs.add(int(m.group(2)))

    for i in sorted(idxs):
        qty = (form.get(f"qty_{i}") or "").strip()
        desc = (form.get(f"desc_{i}") or "").strip()
        key = (form.get(f"key_{i}") or "").strip()
        price = (form.get(f"price_{i}") or "").strip()
        iva = (form.get(f"iva_{i}") or "0.16").strip()
        unit = (form.get(f"unit_{i}") or "").strip()
        disc_pct = (form.get(f"disc_{i}") or "").strip()
        isr_ret = (form.get(f"isr_ret_{i}") or "0").strip()
        iva_ret = (form.get(f"iva_ret_{i}") or "0").strip()

        if not (qty or desc or key or price):
            continue

        if not (qty and desc and key and price and unit):
            raise ValueError(f"Concepto {i}: falta información.")

        disc_pct_num = 0.0
        if disc_pct.strip():
            disc_pct_num = float(disc_pct)
        disc_pct_num = max(0.0, min(100.0, disc_pct_num))

        qty_num = float(qty)
        price_base = float(price)
        iva_rate = float(iva)
        isr_ret_rate = float(isr_ret) if isr_ret else 0.0
        iva_ret_rate = float(iva_ret) if iva_ret else 0.0

        price_to_send = price_base * (1.0 + iva_rate) if iva_rate else price_base
        line_base = qty_num * price_to_send
        line_discount = (disc_pct_num / 100.0) * line_base

        items.append(
            {
                "quantity": qty_num,
                "discount": float(line_discount),
                "product": {
                    "description": desc,
                    "product_key": key,
                    "price": float(price_to_send),
                    "tax_included": True,
                    "taxes": (
                        [{"type": "IVA", "rate": iva_rate}]
                        + ([{"type": "ISR", "rate": isr_ret_rate, "withholding": True}] if isr_ret_rate > 0 else [])
                        + ([{"type": "IVA", "rate": iva_ret_rate, "withholding": True}] if iva_ret_rate > 0 else [])
                    ),
                    "unit_key": unit,
                },
            }
        )

    if not items:
        raise ValueError("Debes capturar al menos un concepto completo.")

    return items


def parse_payments_from_form(form) -> list[dict]:
    idxs = set()
    for k in form.keys():
        m = re.match(r"^pay_uuid_(\d+)$", str(k))
        if m:
            idxs.add(int(m.group(1)))

    related_documents: list[dict] = []
    for i in sorted(idxs):
        uuid = (form.get(f"pay_uuid_{i}") or "").strip()
        amt = (form.get(f"pay_amount_{i}") or "").strip()
        if not (uuid or amt):
            continue
        if not (uuid and amt):
            raise ValueError(f"Pago {i}: falta UUID o monto.")
        amount = float(amt)
        if amount <= 0:
            raise ValueError(f"Pago {i}: monto inválido.")
        related_documents.append({"uuid": uuid, "amount": amount})

    if not related_documents:
        raise ValueError("En Pago (CFDI P) debes seleccionar al menos una factura (UUID) y monto.")

    pay_date = (form.get("pay_date") or "").strip() or None
    pay_currency = (form.get("pay_currency") or "").strip().upper() or None

    payment = {"related_documents": related_documents}
    if pay_date:
        payment["date"] = pay_date
    if pay_currency:
        payment["currency"] = pay_currency

    return [payment]
