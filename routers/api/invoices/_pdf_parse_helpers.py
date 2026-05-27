"""Invoice PDF parsing helpers — orchestrates extraction of structured data from PDF text."""
import re

from routers.api.invoices._pdf_amounts import (
    _clean_item_desc,
    _extract_amounts_from_tables,
    _extract_items_from_text,
    _parse_amount,
)
from routers.api.invoices._pdf_text import (
    _COUNTRY_MAP,
    _MONTH_MAP,
    _extract_company_name,
    _parse_date,
)
from routers.api.invoices._pdf_tipo_detect import _detect_tipo  # noqa: F401 — re-exported for tests


def _parse_invoice_text(text: str, tables: list | None = None, issuer_context: dict | None = None) -> dict:
    """Parse invoice text and extract structured fields."""
    result: dict = {
        "invoice_number": None,
        "fecha": None,
        "empresa": None,
        "pais": None,
        "moneda": None,
        "monto_original": None,
        "descripcion": None,
        "tax_id": None,
        "productos": [],
        "forma_pago": None,
        "tipo": None,
    }
    lines = [l.strip() for l in text.strip().split("\n") if l.strip()]

    # -- Invoice number --
    _NOT_INVOICE_NUM = {"order", "seller", "receipt", "invoice", "date", "from", "to", "item", "price", "total", "paid", "id",
                         "number", "details", "summary", "description", "amount", "created", "status", "type"}
    for pat in [
        r"(?:Invoice|Inv|Factura|Receipt|Bill|Rechnung|Nota)\s*(?:#|No\.?|Number|Num|Número|Nr\.?)\s*[:\s]*([A-Za-z0-9][\w\-\/\.]+)",
        r"(?:Invoice\s+ID|Order\s+ID|Order\s*#|Ref|Reference|Referencia)\s*[:\s#]*([A-Za-z0-9][\w\-\/\.]+)",
        r"(?:Invoice|INV|FACTURA|RECEIPT)[ \t]*[:#\-]+[:#\- \t]*([A-Za-z0-9][\w\-\/\.]+)",
        r"(?:Invoice|Factura)\s+([A-Za-z0-9][\w\-]{3,30})",
        r"#\s*([A-Z0-9][\w\-]{2,20})",
    ]:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            val = m.group(1).strip().rstrip(".")
            if len(val) >= 2 and val.lower() not in _NOT_INVOICE_NUM:
                result["invoice_number"] = val
                break

    # -- Date --
    _DATE_LABEL = (
        r"(?:Date|Fecha|Invoice\s*Date|Issue\s*Date|Datum|"
        r"Issued\s*(?:at|on)?|Billed\s*(?:On|Date)?|"
        r"Order\s*Created|Paid\s*(?:on|In\s*Full)?|Due\s*(?:On|Date)?)"
    )
    date_patterns = [
        _DATE_LABEL + r"\s*[:\s]+(\d{4}-\d{2}-\d{2})",
        _DATE_LABEL + r"\s*[:\s]+(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4})",
        _DATE_LABEL + r"\s*[:\s]+(\w+\s+\d{1,2}(?:st|nd|rd|th)?,?\s*\d{4})",
        _DATE_LABEL + r"\s*[:\s]+(\d{1,2}(?:st|nd|rd|th)?\s+\w+,?\s*\d{4})",
        r"(\d{4}-\d{2}-\d{2})",
        r"(\w+\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4})",
        r"(\d{1,2}(?:st|nd|rd|th)?\s+\w+\s+\d{4})",
        r"(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{4})",
    ]
    for pat in date_patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            parsed = _parse_date(m.group(1))
            if parsed and re.match(r"\d{4}-\d{2}-\d{2}$", parsed):
                result["fecha"] = parsed
                break
            elif parsed:
                result["fecha"] = parsed
                break

    # -- Currency --
    if re.search(r"\bUSD\b|\bUS\s*\$|\bUS\s*Dollar", text, re.IGNORECASE):
        result["moneda"] = "USD"
    elif re.search(r"\bEUR\b|€|\bEuro\b", text, re.IGNORECASE):
        result["moneda"] = "EUR"
    elif re.search(r"\bGBP\b|£|\bPound\s*Sterling", text, re.IGNORECASE):
        result["moneda"] = "GBP"
    elif re.search(r"\bCAD\b|\bCanadian\s*Dollar", text, re.IGNORECASE):
        result["moneda"] = "CAD"
    elif re.search(r"\bCHF\b|\bSwiss\s*Franc", text, re.IGNORECASE):
        result["moneda"] = "CHF"
    elif re.search(r"\$", text) and not re.search(r"\bMXN\b|\bpeso", text, re.IGNORECASE):
        result["moneda"] = "USD"

    # -- Total amount --
    amount_patterns = [
        r"(?:Grand\s*Total|Amount\s*Due|Balance\s*Due|Total\s*Due|Total\s*a\s*Pagar|Importe\s*Total)\s*[:\s]*[€$£]?\s*([\d.,]+)",
        r"(?<![Ss]ub)\bTotal\s*[:\s]*[€$£]?\s*([\d.,]+)",
        r"(?<![Ss]ub)\b(?:Total|Amount)\s*[:\s]*(?:USD|EUR|GBP|CAD)?\s*[€$£]?\s*([\d.,]+)",
    ]
    best_total = None
    for pat in amount_patterns:
        matches = list(re.finditer(pat, text, re.IGNORECASE))
        if matches:
            raw = matches[-1].group(1)
            val = _parse_amount(raw)
            if val and val > 0:
                if best_total is None or (pat == amount_patterns[0]):
                    best_total = val
                    break
    if best_total:
        result["monto_original"] = best_total

    # -- Company name --
    result["empresa"] = _extract_company_name(lines, text)

    # -- Tax ID --
    tax_patterns = [
        r"(?:Tax\s*ID|EIN|VAT\s*(?:No\.?|Number|ID)?|TIN|RFC|GST\s*(?:No\.?)?|ABN|NIF|CIF|GSTIN|Tax\s*Number|Tax\s*Reg)\s*[:\s#]*([A-Za-z0-9][\w\-\.]{3,25})",
        r"(?:Tax\s*Registration)\s*[:\s]*([A-Za-z0-9][\w\-\.]{3,25})",
    ]
    for pat in tax_patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            result["tax_id"] = m.group(1).strip()
            break

    # -- Products / line items --
    # Priority 1: pdfplumber tables
    table_items = _extract_amounts_from_tables(tables or [])
    if table_items:
        result["productos"] = [it["descripcion"] for it in table_items if it.get("descripcion")]
        if not result["monto_original"]:
            table_sum = sum(it.get("monto") or 0 for it in table_items)
            if table_sum > 0:
                result["monto_original"] = table_sum

    # Priority 2: Text-based extraction
    if not result["productos"]:
        items_collected = _extract_items_from_text(lines)
        if items_collected:
            result["productos"] = items_collected

    # Priority 3: Single labeled description
    if not result["productos"]:
        for pat in [
            r"(?:Item|Product|Service|Concept|Concepto)\s*[:\s]+([^\n]{5,})",
            r"(?:Detalle|Partida|Línea)\s*[:\s]+([^\n]{5,})",
        ]:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                desc = _clean_item_desc(m.group(1).strip())
                if desc and len(desc) > 3:
                    result["productos"] = [desc[:200]]
                    break

    # -- Description --
    if result["productos"]:
        result["descripcion"] = "; ".join(result["productos"])[:200]
    else:
        desc_patterns = [
            r"(?:Description|Service|Concept|Descripción|Concepto|Memo|Notes?|Subject|Regarding|Re:)\s*[:\s]*\n?\s*(.+)",
            r"(?:For|Por)\s*[:\s]+(.{10,})",
        ]
        for pat in desc_patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                desc = m.group(1).strip()
                desc = re.split(r"\s{2,}|\t", desc)[0].strip()
                if len(desc) > 3:
                    result["descripcion"] = desc[:200]
                    break

    # -- Country --
    for name, code in _COUNTRY_MAP.items():
        if re.search(r"\b" + re.escape(name) + r"\b", text, re.IGNORECASE):
            result["pais"] = code
            break
    if not result["pais"] and re.search(r"\b(?:CA|NY|TX|FL|IL|WA|MA|PA|OH|GA|NC|NJ|VA|AZ|CO|TN)\s+\d{5}", text):
        result["pais"] = "US"

    # -- Payment method --
    pay_text = text.lower()
    if "swift" in pay_text or "wire transfer" in pay_text or "bank transfer" in pay_text or "transferencia" in pay_text:
        result["forma_pago"] = "SWIFT"
    elif "paypal" in pay_text:
        result["forma_pago"] = "PayPal"
    elif "wise" in pay_text or "transferwise" in pay_text:
        result["forma_pago"] = "Wise"
    elif "stripe" in pay_text:
        result["forma_pago"] = "Stripe"
    elif "payoneer" in pay_text:
        result["forma_pago"] = "Payoneer"
    elif re.search(r"\bcredit\s*card|tarjeta|visa|mastercard|amex", pay_text):
        result["forma_pago"] = "CREDITO"

    # -- Type (INGRESO vs GASTO) --
    result["tipo"] = _detect_tipo(text, issuer_context)

    return result
