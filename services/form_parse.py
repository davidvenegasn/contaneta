"""Parseo de formularios de factura (conceptos y pagos CFDI P)."""
import re
from typing import List


def _sanitize_sat_code(raw: str) -> str:
    """Strip everything except the first alphanumeric token.

    The datalist autocomplete in the invoice form lets the user pick an
    option whose label is "84111506 — Servicios contables", which sets
    the input value to the whole label string. Facturapi rejects anything
    non-alphanumeric in product_key / unit_key. SAT codes are short
    alphanumeric tokens (typically 8 digits for ProdServ, 1-3 chars for
    Unidad), so taking the first token is correct and robust.
    """
    if not raw:
        return ""
    m = re.match(r"\s*([A-Za-z0-9]+)", str(raw))
    return m.group(1) if m else ""


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
        key = _sanitize_sat_code(form.get(f"key_{i}") or "")
        price = (form.get(f"price_{i}") or "").strip()
        iva = (form.get(f"iva_{i}") or "0.16").strip()
        unit = _sanitize_sat_code(form.get(f"unit_{i}") or "")
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
        isr_ret_rate = float(isr_ret) if isr_ret else 0.0
        iva_ret_rate = float(iva_ret) if iva_ret else 0.0

        is_exento = iva.upper() == "EXENTO"
        iva_rate = 0.0 if is_exento else float(iva)

        # price sent to Facturapi includes IVA (tax_included=True)
        price_to_send = price_base * (1.0 + iva_rate) if iva_rate else price_base
        line_base = qty_num * price_to_send
        line_discount = (disc_pct_num / 100.0) * line_base

        if is_exento:
            iva_taxes = [{"type": "IVA", "factor": "Exempt"}]
        else:
            iva_taxes = [{"type": "IVA", "rate": iva_rate}]

        # ObjetoImp (CFDI 4.0 c_ObjetoImp) — auto-detect per line.
        # "02" = sí objeto de impuesto (cualquier IVA trasladado o exento, o retenciones)
        # "01" = no objeto de impuesto (cero IVA y sin retenciones)
        # Override via form field `objeto_imp_{i}` if user picked manually.
        has_any_tax = is_exento or iva_rate > 0 or isr_ret_rate > 0 or iva_ret_rate > 0
        objeto_imp_override = (form.get(f"objeto_imp_{i}") or "").strip()
        objeto_imp = objeto_imp_override or ("02" if has_any_tax else "01")

        items.append(
            {
                "quantity": qty_num,
                "discount": float(line_discount),
                "product": {
                    "description": desc,
                    "product_key": key,
                    "price": float(price_to_send),
                    "tax_included": True,
                    "tax_objet": objeto_imp,  # Facturapi field for c_ObjetoImp
                    "taxes": (
                        iva_taxes
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
