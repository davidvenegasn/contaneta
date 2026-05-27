"""PDF amount parsing — currency detection, amount extraction, line items from tables and text."""
import re


def _parse_amount(raw: str) -> float | None:
    """Parse an amount string handling US and EU formats."""
    raw = raw.strip()
    # Remove currency symbols
    raw = re.sub(r"[€$£¥]", "", raw).strip()
    raw = re.sub(r"^(USD|EUR|GBP|CAD|MXN)\s*", "", raw, flags=re.IGNORECASE).strip()
    raw = re.sub(r"\s*(USD|EUR|GBP|CAD|MXN)$", "", raw, flags=re.IGNORECASE).strip()
    if not raw:
        return None
    # European: 1.234,56 -> 1234.56
    if re.match(r"[\d\.]+,\d{2}$", raw):
        raw = raw.replace(".", "").replace(",", ".")
    else:
        raw = raw.replace(",", "")
    try:
        v = float(raw)
        return v if v > 0 else None
    except ValueError:
        return None


def _extract_amounts_from_tables(tables: list) -> list[dict]:
    """Extract item descriptions and amounts from pdfplumber tables."""
    items: list[dict] = []
    for table in tables:
        if not table or len(table) < 2:
            continue
        header = table[0]
        if not header:
            continue
        # Find description and amount columns by header text
        desc_col = amt_col = qty_col = rate_col = None
        header_lower = [(str(h or "").lower().strip()) for h in header]
        for i, h in enumerate(header_lower):
            if any(k in h for k in (
                "description", "item", "service", "concept", "producto", "descripci",
                "detalle", "partida", "product", "line item", "memo", "nombre",
            )):
                desc_col = i
            if any(k in h for k in ("amount", "total", "monto", "importe", "betrag", "sum")):
                amt_col = i
            if any(k in h for k in ("qty", "quantity", "cantidad", "menge", "units", "hours", "hrs")):
                qty_col = i
            if any(k in h for k in ("rate", "price", "precio", "unit", "preis", "cost", "tarifa")):
                rate_col = i
        if desc_col is None:
            # Try first text column
            for i, h in enumerate(header_lower):
                if h and not any(c.isdigit() for c in h):
                    desc_col = i
                    break
        if amt_col is None and rate_col is not None:
            amt_col = rate_col
        for row in table[1:]:
            if not row:
                continue
            desc = str(row[desc_col] or "").strip() if desc_col is not None and desc_col < len(row) else ""
            amt_str = str(row[amt_col] or "").strip() if amt_col is not None and amt_col < len(row) else ""
            # Skip subtotal/total/tax rows in table items
            if desc and re.match(r"^(subtotal|total|tax|iva|vat|impuesto|descuento|discount|shipping|envío)", desc, re.IGNORECASE):
                continue
            if desc and len(desc) > 2:
                amt = _parse_amount(amt_str) if amt_str else None
                items.append({"descripcion": desc, "monto": amt})
    return items


_ITEM_HEADER_RE = re.compile(
    r"^(?:Description|Items?\b|Item\s*Description|Line\s*Items?|Services?|"
    r"Concepto|Descripción|Descripcion|Productos?|Detalle|Partida|"
    r"Service\s*Description|Product\s*Name|Product|"
    r"#\s+Description|#\s+Item|No\.\s+Description)",
    re.IGNORECASE,
)
_TABLE_COL_WORDS = {
    "qty", "quantity", "rate", "price", "amount", "unit", "total",
    "hrs", "hours", "cantidad", "precio", "monto", "importe",
    "menge", "preis", "betrag", "#", "no", "no.",
}
_ITEMS_END_RE = re.compile(
    r"^(?:Subtotal|Sub\s*Total|Total|Tax|IVA|VAT|Discount|Descuento|"
    r"Shipping|Envío|Notes?|Terms|Payment|Thank|Gracias|Bank|IBAN|SWIFT)\b",
    re.IGNORECASE,
)


def _clean_item_desc(raw: str) -> str:
    """Strip trailing qty/rate/amount numbers from an item description line."""
    s = raw
    for _ in range(8):
        prev = s
        s = re.sub(r"\s+[\$€£][\d,\.]+\s*$", "", s).strip()
        s = re.sub(r"\s+[\d,]+\.\d{2}\s*$", "", s).strip()
        s = re.sub(r"\s+\d{1,4}\s*$", "", s).strip()
        s = re.sub(r"\s+\d{1,6}\s+(?:hrs?|units?|pcs?|ea|GB|TB|MB|KB)\s*$", "", s, flags=re.IGNORECASE).strip()
        s = re.sub(r"\s+x\s*\d+\s*$", "", s, flags=re.IGNORECASE).strip()
        s = re.sub(r"\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+\d{4}\s*$", "", s, flags=re.IGNORECASE).strip()
        if s == prev:
            break
    return s


def _extract_items_from_text(lines: list[str]) -> list[str]:
    """Extract product/service descriptions from text-based item sections.

    Returns:
        List of item description strings (max 10).
    """
    in_items = False
    items_collected = []
    for line in lines:
        if _ITEM_HEADER_RE.match(line):
            in_items = True
            continue
        if not in_items:
            continue
        if _ITEMS_END_RE.match(line):
            break
        if len(line) < 3:
            continue
        parts = re.split(r"\s{2,}|\t", line)
        desc_part = parts[0].strip() if parts else ""
        if not desc_part or len(desc_part) < 2:
            continue
        if re.match(r"^[\d\$€£\.,\s\-]+$", desc_part):
            continue
        words = [w.lower().rstrip(".") for w in desc_part.split()]
        if words and all(w in _TABLE_COL_WORDS for w in words):
            continue
        desc_clean = _clean_item_desc(desc_part)
        if desc_clean and len(desc_clean) > 2:
            items_collected.append(desc_clean)
    return items_collected[:10]
