"""Invoice PDF parsing helpers — pure functions for extracting structured data from PDF text."""
import re
import unicodedata

_MONTH_MAP = {
    "january": "01", "february": "02", "march": "03", "april": "04",
    "may": "05", "june": "06", "july": "07", "august": "08",
    "september": "09", "october": "10", "november": "11", "december": "12",
    "jan": "01", "feb": "02", "mar": "03", "apr": "04",
    "jun": "06", "jul": "07", "aug": "08", "sep": "09",
    "oct": "10", "nov": "11", "dec": "12",
    "enero": "01", "febrero": "02", "marzo": "03", "abril": "04",
    "mayo": "05", "junio": "06", "julio": "07", "agosto": "08",
    "septiembre": "09", "octubre": "10", "noviembre": "11", "diciembre": "12",
}

_COUNTRY_MAP = {
    "United States": "US", "USA": "US", "U.S.A.": "US", "U.S.": "US",
    "Canada": "CA", "United Kingdom": "GB", "UK": "GB", "Great Britain": "GB",
    "Germany": "DE", "Deutschland": "DE", "France": "FR",
    "Spain": "ES", "España": "ES",
    "Colombia": "CO", "Argentina": "AR", "Chile": "CL",
    "Brazil": "BR", "Brasil": "BR",
    "Mexico": "MX", "México": "MX",
    "Italy": "IT", "Italia": "IT",
    "Netherlands": "NL", "Portugal": "PT",
    "Australia": "AU", "New Zealand": "NZ",
    "Japan": "JP", "China": "CN", "India": "IN",
    "Ireland": "IE", "Switzerland": "CH",
    "Israel": "IL", "Singapore": "SG",
    "Denmark": "DK", "Danmark": "DK", "DENMARK": "DK",
    "Sweden": "SE", "Norway": "NO", "Finland": "FI",
    "Belgium": "BE", "Austria": "AT",
}

_COMPANY_SUFFIXES = re.compile(
    r"\b(?:Inc\.?|LLC|Ltd\.?|Corp\.?|GmbH|SA\b|S\.?A\.?\s*de\s*C\.?V\.?|"
    r"S\.?L\.?|S\.?R\.?L\.?|Co\.?|PLC|AG|BV|NV|Pty|Limited|Corporation|Company|Incorporated)\b",
    re.IGNORECASE,
)

_SKIP_HEADER_RE = re.compile(
    r"^(?:Invoice|Date|Bill\s*To|Ship\s*To|To:|Sold\s*To|Remit|Due|Terms|Page|P\.?O\.?\s|"
    r"Phone|Fax|Email|Tel|www\.|http|Tax\s*ID|EIN|VAT|TIN|Subtotal|Total|\d{1,2}[/\-\.]\d|"
    r"\d{4}-\d{2}|Amount|Payment|Balance|Description|Item|Qty|Quantity|Rate|Price|Unit|"
    r"Issued|Paid|Order|Status|Account|Billing|Receipt|Ref|Reference|"
    r"Statement|Period|Subscription|Thank|Dear|Hello|Hi\b|Note|Memo)",
    re.IGNORECASE,
)


def _parse_date(raw: str) -> str | None:
    """Try to normalize a date string to YYYY-MM-DD."""
    raw = raw.strip()
    # Strip ordinal suffixes: 24th -> 24, 1st -> 1, 2nd -> 2, 3rd -> 3
    cleaned = re.sub(r"(\d{1,2})(?:st|nd|rd|th)\b", r"\1", raw)
    # ISO
    if re.match(r"\d{4}-\d{2}-\d{2}$", cleaned):
        return cleaned
    # Named month: "15 March 2024" / "15 March, 2024"
    m = re.match(r"(\d{1,2})\s+(\w+),?\s+(\d{4})$", cleaned)
    if m:
        day, mon, year = m.group(1), m.group(2).lower(), m.group(3)
        if mon in _MONTH_MAP:
            return f"{year}-{_MONTH_MAP[mon]}-{day.zfill(2)}"
    # Named month: "March 15, 2024" / "March 15 2024"
    m = re.match(r"(\w+)\s+(\d{1,2}),?\s+(\d{4})$", cleaned)
    if m:
        mon, day, year = m.group(1).lower(), m.group(2), m.group(3)
        if mon in _MONTH_MAP:
            return f"{year}-{_MONTH_MAP[mon]}-{day.zfill(2)}"
    # DD/MM/YYYY or MM/DD/YYYY (also handles 2-digit year)
    parts = re.split(r"[/\-\.]", cleaned)
    if len(parts) == 3:
        if len(parts[2]) == 2:
            parts[2] = "20" + parts[2]
        try:
            a, b, c = int(parts[0]), int(parts[1]), int(parts[2])
        except ValueError:
            return cleaned
        if c > 1900:
            if a > 12:  # DD/MM/YYYY
                return f"{c}-{str(b).zfill(2)}-{str(a).zfill(2)}"
            else:  # MM/DD/YYYY (US default)
                return f"{c}-{str(a).zfill(2)}-{str(b).zfill(2)}"
        elif a > 1900:  # YYYY/MM/DD
            return f"{a}-{str(b).zfill(2)}-{str(c).zfill(2)}"
    return cleaned


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


_BILL_TO_MARKER = re.compile(
    r"^(?:Bill\s*To|Billed?\s*To|Sold\s*To|Ship\s*To|Invoice\s*To|Purchaser|Customer|Comprador|Cliente|To:)\b",
    re.IGNORECASE,
)


def _normalize_for_match(s: str) -> str:
    """Lowercase, strip accents, strip punctuation for fuzzy name matching."""
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")  # strip accents
    s = re.sub(r"[^\w\s]", " ", s.lower())
    return " ".join(s.split())


def _name_words(name: str) -> list[str]:
    """Extract significant words (>= 2 chars) from a normalized name."""
    return [w for w in _normalize_for_match(name).split() if len(w) >= 2]


def _words_match(needle_words: list[str], haystack: str, min_matches: int = 2) -> bool:
    """Check if at least `min_matches` words from needle appear in haystack."""
    if not needle_words:
        return False
    hay = _normalize_for_match(haystack)
    hits = sum(1 for w in needle_words if w in hay)
    # For single-word names (e.g. "Stripe"), require just 1 match
    needed = min(min_matches, len(needle_words))
    return hits >= needed


def _detect_tipo(text: str, issuer_context: dict | None) -> str | None:
    """Detect INGRESO vs GASTO by comparing issuer name against PDF sections.

    Returns:
        "INGRESO" if the issuer appears to be the seller (name in header).
        "GASTO" if the issuer appears to be the buyer (name in bill-to section).
        None if it cannot be determined.
    """
    if not issuer_context:
        return None
    issuer_name = (
        issuer_context.get("razon_social")
        or issuer_context.get("nombre")
        or ""
    ).strip()
    if len(issuer_name) < 2:
        return None

    words = _name_words(issuer_name)
    if not words:
        return None

    lines = [l.strip() for l in text.strip().split("\n") if l.strip()]

    # Split text into seller block (before Bill To) and buyer block (after Bill To)
    seller_lines: list[str] = []
    buyer_lines: list[str] = []
    bill_to_idx = None
    for i, line in enumerate(lines[:30]):
        if _BILL_TO_MARKER.match(line):
            bill_to_idx = i
            break
        seller_lines.append(line)

    if bill_to_idx is not None:
        # Collect buyer lines: up to 8 lines after "Bill To" marker, stop at next section
        for line in lines[bill_to_idx + 1: bill_to_idx + 9]:
            if re.match(r"^(?:Invoice|Date|Due|Terms|Payment|Amount|Total|Item|Description|#)\b", line, re.IGNORECASE):
                break
            buyer_lines.append(line)

    seller_text = " ".join(seller_lines[:10])
    buyer_text = " ".join(buyer_lines)

    in_seller = _words_match(words, seller_text)
    in_buyer = _words_match(words, buyer_text)

    if in_seller and not in_buyer:
        return "INGRESO"
    if in_buyer and not in_seller:
        return "GASTO"
    # Ambiguous or no match
    return None


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
    # Known keywords that are NOT invoice numbers
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
        # Labeled dates
        _DATE_LABEL + r"\s*[:\s]+(\d{4}-\d{2}-\d{2})",
        _DATE_LABEL + r"\s*[:\s]+(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4})",
        _DATE_LABEL + r"\s*[:\s]+(\w+\s+\d{1,2}(?:st|nd|rd|th)?,?\s*\d{4})",
        _DATE_LABEL + r"\s*[:\s]+(\d{1,2}(?:st|nd|rd|th)?\s+\w+,?\s*\d{4})",
        # Unlabeled ISO
        r"(\d{4}-\d{2}-\d{2})",
        # Unlabeled named month (with optional ordinal suffix)
        r"(\w+\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4})",
        r"(\d{1,2}(?:st|nd|rd|th)?\s+\w+\s+\d{4})",
        # Unlabeled numeric
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

    # -- Currency (detect early, affects amount parsing) --
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
        result["moneda"] = "USD"  # $ without MXN context -> USD

    # -- Total amount (find the grand total, not subtotals) --
    amount_patterns = [
        # Specific "grand total" / "balance due" / "amount due" (most specific)
        r"(?:Grand\s*Total|Amount\s*Due|Balance\s*Due|Total\s*Due|Total\s*a\s*Pagar|Importe\s*Total)\s*[:\s]*[€$£]?\s*([\d.,]+)",
        # "Total" (not Subtotal) at end of document (reverse search -- last match wins)
        r"(?<![Ss]ub)\bTotal\s*[:\s]*[€$£]?\s*([\d.,]+)",
        # Amount with currency symbol/code
        r"(?<![Ss]ub)\b(?:Total|Amount)\s*[:\s]*(?:USD|EUR|GBP|CAD)?\s*[€$£]?\s*([\d.,]+)",
    ]
    # For "Total", prefer the LAST occurrence (usually the grand total)
    best_total = None
    for pat in amount_patterns:
        matches = list(re.finditer(pat, text, re.IGNORECASE))
        if matches:
            # Use last match for "Total" (grand total usually at bottom)
            raw = matches[-1].group(1)
            val = _parse_amount(raw)
            if val and val > 0:
                if best_total is None or (pat == amount_patterns[0]):
                    best_total = val
                    break
    if best_total:
        result["monto_original"] = best_total

    # -- Company name --
    # The company name is almost always the FIRST line of the PDF
    # (the sender/issuer puts their name at the top).

    # Strategy 1: "Invoice from X" / "Bill From: X" (explicit label)
    from_m = re.search(
        r"(?:Invoice\s+from|Bill\s*From|Billed?\s*By|Issued\s*By|Seller|Emisor|Proveedor)\s*[:\s]+(.+)",
        text, re.IGNORECASE,
    )
    if from_m:
        name = re.split(r"\s{2,}|\t|\|", from_m.group(1).strip())[0].strip()
        if 2 < len(name) < 120 and not re.match(r"^\d", name):
            result["empresa"] = name

    # Strategy 2: First line of the document (most common -- company name at top)
    _MONTH_NAMES_RE = re.compile(
        r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December|"
        r"Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\b", re.IGNORECASE,
    )
    # Detect "Bill To" / "Billed To" zone -- lines after this are the BUYER, not the seller
    _BILL_TO_RE = re.compile(r"^(?:Bill\s*To|Billed?\s*To|Sold\s*To|Ship\s*To|Purchaser|Customer|Comprador|Cliente)\b", re.IGNORECASE)
    _SELLER_RE = re.compile(r"^(?:Seller|From|Bill\s*From|Billed?\s*By|Issued\s*By|Vendor|Emisor|Proveedor)\b", re.IGNORECASE)
    if not result["empresa"]:
        in_bill_to = False
        after_email = 0  # count lines after an email (likely buyer info)
        for line in lines[:20]:
            # Track bill-to / seller sections
            if _BILL_TO_RE.match(line):
                in_bill_to = True
                continue
            if _SELLER_RE.match(line):
                in_bill_to = False
                after_email = 0
                continue
            # Skip blank separator lines that might end the bill-to zone
            if in_bill_to:
                # Country names or short location lines end the zone
                if re.match(r"^[A-Z]{2,}$", line) and len(line) <= 30:
                    in_bill_to = False
                continue
            # After an email line, skip 1-2 lines (likely buyer name + country)
            if after_email > 0:
                after_email -= 1
                # ALL-CAPS country name ends the post-email skip zone
                if re.match(r"^[A-Z]{2,}$", line) and len(line) <= 30:
                    after_email = 0
                continue
            if len(line) < 2 or len(line) > 120:
                continue
            if _SKIP_HEADER_RE.match(line):
                continue
            # Skip lines that are just numbers/dates
            if re.match(r"^[\d\s\-/\.\,\(\):]+$", line):
                continue
            # Skip date-range lines: "February 24th 2026 to March 23rd 2026"
            month_hits = _MONTH_NAMES_RE.findall(line)
            if len(month_hits) >= 2:
                continue
            # Skip lines that are a date with some label: "Issued at: 2026-02-17"
            if re.search(r"\d{4}-\d{2}-\d{2}", line) and len(line) < 60:
                continue
            # Skip lines with "Paid", "Issued", date references
            if re.match(r"^(?:Paid|Issued|Order|Status|Account|Billing|Period|Statement|Receipt)\b", line, re.IGNORECASE):
                continue
            # Skip lines containing email addresses or URLs
            if "@" in line:
                after_email = 2  # skip next 1-2 lines (buyer name + country)
                continue
            if re.search(r"https?://|www\.", line, re.IGNORECASE):
                continue
            # Skip address lines (start with number + street name)
            if re.match(r"^\d+\s+\w+\s+(St|Ave|Blvd|Dr|Road|Rd|Lane|Ln|Way|Calle|Av|Col)\b", line, re.IGNORECASE):
                continue
            # Skip lines that look like dates: "Month Nth, YYYY", "YYYY-MM-DD", etc.
            if re.match(r"^\w+\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4}", line, re.IGNORECASE):
                continue
            # Skip lines that contain a month name + year (likely date/period info)
            if _MONTH_NAMES_RE.search(line) and re.search(r"\d{4}", line):
                continue
            result["empresa"] = line
            break

    # Strategy 3: Line containing a company suffix (Inc., LLC, GmbH, etc.)
    if not result["empresa"]:
        for line in lines[:15]:
            if _COMPANY_SUFFIXES.search(line):
                name = re.sub(r"^[\d\.\)\-]+\s*", "", line).strip()
                if 3 < len(name) < 120:
                    result["empresa"] = name
                    break

    # Clean empresa: strip trailing INVOICE / RECEIPT / FACTURA labels
    if result["empresa"]:
        result["empresa"] = re.sub(
            r"\s*[-–|]\s*(?:INVOICE|RECEIPT|FACTURA|RECHNUNG|BILL|NOTA)\s*$",
            "", result["empresa"], flags=re.IGNORECASE,
        ).strip()
        result["empresa"] = re.sub(
            r"\s+(?:INVOICE|RECEIPT|FACTURA|RECHNUNG|BILL|NOTA)\s*$",
            "", result["empresa"], flags=re.IGNORECASE,
        ).strip()

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
    # Priority 1: pdfplumber tables (most reliable for structured invoices)
    table_items = _extract_amounts_from_tables(tables or [])
    if table_items:
        result["productos"] = [it["descripcion"] for it in table_items if it.get("descripcion")]
        if not result["monto_original"]:
            table_sum = sum(it.get("monto") or 0 for it in table_items)
            if table_sum > 0:
                result["monto_original"] = table_sum

    # Priority 2: Text-based extraction -- find items section
    # Detect the start of the items section by looking for table headers
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
            # $1,234.56 or EUR1.234,56
            s = re.sub(r"\s+[\$€£][\d,\.]+\s*$", "", s).strip()
            # 1,234.56 or 1234.56 (bare amounts)
            s = re.sub(r"\s+[\d,]+\.\d{2}\s*$", "", s).strip()
            # Bare integers (qty)
            s = re.sub(r"\s+\d{1,4}\s*$", "", s).strip()
            # "40 hrs" / "2 units" / "500 GB"
            s = re.sub(r"\s+\d{1,6}\s+(?:hrs?|units?|pcs?|ea|GB|TB|MB|KB)\s*$", "", s, flags=re.IGNORECASE).strip()
            # "x 2" or "x2"
            s = re.sub(r"\s+x\s*\d+\s*$", "", s, flags=re.IGNORECASE).strip()
            # Period/date fragments like "Jan 2026"
            s = re.sub(r"\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+\d{4}\s*$", "", s, flags=re.IGNORECASE).strip()
            if s == prev:
                break
        return s

    if not result["productos"]:
        in_items = False
        items_collected = []
        for line in lines:
            # Detect items section start
            if _ITEM_HEADER_RE.match(line):
                in_items = True
                continue
            if not in_items:
                continue
            # Detect items section end
            if _ITEMS_END_RE.match(line):
                break
            # Skip empty / tiny lines
            if len(line) < 3:
                continue
            # Split on wide spaces/tabs to get columns
            parts = re.split(r"\s{2,}|\t", line)
            desc_part = parts[0].strip() if parts else ""
            if not desc_part or len(desc_part) < 2:
                continue
            # Skip lines that are only numbers/currency
            if re.match(r"^[\d\$€£\.,\s\-]+$", desc_part):
                continue
            # Skip sub-header rows (all words are column header words)
            words = [w.lower().rstrip(".") for w in desc_part.split()]
            if words and all(w in _TABLE_COL_WORDS for w in words):
                continue
            # Clean trailing numeric columns
            desc_clean = _clean_item_desc(desc_part)
            if desc_clean and len(desc_clean) > 2:
                items_collected.append(desc_clean)
        if items_collected:
            result["productos"] = items_collected[:10]

    # Priority 3: Single labeled description (no table/list)
    # e.g. "Item: Cloud Hosting Service" or "For: Website Development"
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

    # -- Description (build from products or labeled section) --
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
    # Detect from state abbreviations (US)
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
    # Compare issuer name against seller/buyer sections of the PDF.
    # None = undetectable → UI defaults to INGRESO (common for freelancers).
    result["tipo"] = _detect_tipo(text, issuer_context)

    return result
