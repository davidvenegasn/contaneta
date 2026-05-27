"""PDF text parsing utilities — date parsing, company name extraction, constants."""
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


def _extract_company_name(lines: list[str], text: str) -> str | None:
    """Extract company name from invoice text using multiple strategies.

    Args:
        lines: Pre-split text lines (stripped).
        text: Full raw text for regex searches.

    Returns:
        Company name string, or None if not detected.
    """
    empresa = None

    # Strategy 1: "Invoice from X" / "Bill From: X" (explicit label)
    from_m = re.search(
        r"(?:Invoice\s+from|Bill\s*From|Billed?\s*By|Issued\s*By|Seller|Emisor|Proveedor)\s*[:\s]+(.+)",
        text, re.IGNORECASE,
    )
    if from_m:
        name = re.split(r"\s{2,}|\t|\|", from_m.group(1).strip())[0].strip()
        if 2 < len(name) < 120 and not re.match(r"^\d", name):
            empresa = name

    # Strategy 2: First line of the document (most common -- company name at top)
    _MONTH_NAMES_RE = re.compile(
        r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December|"
        r"Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\b", re.IGNORECASE,
    )
    _BILL_TO_RE = re.compile(r"^(?:Bill\s*To|Billed?\s*To|Sold\s*To|Ship\s*To|Purchaser|Customer|Comprador|Cliente)\b", re.IGNORECASE)
    _SELLER_RE = re.compile(r"^(?:Seller|From|Bill\s*From|Billed?\s*By|Issued\s*By|Vendor|Emisor|Proveedor)\b", re.IGNORECASE)
    if not empresa:
        in_bill_to = False
        after_email = 0
        for line in lines[:20]:
            if _BILL_TO_RE.match(line):
                in_bill_to = True
                continue
            if _SELLER_RE.match(line):
                in_bill_to = False
                after_email = 0
                continue
            if in_bill_to:
                if re.match(r"^[A-Z]{2,}$", line) and len(line) <= 30:
                    in_bill_to = False
                continue
            if after_email > 0:
                after_email -= 1
                if re.match(r"^[A-Z]{2,}$", line) and len(line) <= 30:
                    after_email = 0
                continue
            if len(line) < 2 or len(line) > 120:
                continue
            if _SKIP_HEADER_RE.match(line):
                continue
            if re.match(r"^[\d\s\-/\.\,\(\):]+$", line):
                continue
            month_hits = _MONTH_NAMES_RE.findall(line)
            if len(month_hits) >= 2:
                continue
            if re.search(r"\d{4}-\d{2}-\d{2}", line) and len(line) < 60:
                continue
            if re.match(r"^(?:Paid|Issued|Order|Status|Account|Billing|Period|Statement|Receipt)\b", line, re.IGNORECASE):
                continue
            if "@" in line:
                after_email = 2
                continue
            if re.search(r"https?://|www\.", line, re.IGNORECASE):
                continue
            if re.match(r"^\d+\s+\w+\s+(St|Ave|Blvd|Dr|Road|Rd|Lane|Ln|Way|Calle|Av|Col)\b", line, re.IGNORECASE):
                continue
            if re.match(r"^\w+\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4}", line, re.IGNORECASE):
                continue
            if _MONTH_NAMES_RE.search(line) and re.search(r"\d{4}", line):
                continue
            empresa = line
            break

    # Strategy 3: Line containing a company suffix (Inc., LLC, GmbH, etc.)
    if not empresa:
        for line in lines[:15]:
            if _COMPANY_SUFFIXES.search(line):
                name = re.sub(r"^[\d\.\)\-]+\s*", "", line).strip()
                if 3 < len(name) < 120:
                    empresa = name
                    break

    # Clean empresa: strip trailing INVOICE / RECEIPT / FACTURA labels
    if empresa:
        empresa = re.sub(
            r"\s*[-–|]\s*(?:INVOICE|RECEIPT|FACTURA|RECHNUNG|BILL|NOTA)\s*$",
            "", empresa, flags=re.IGNORECASE,
        ).strip()
        empresa = re.sub(
            r"\s+(?:INVOICE|RECEIPT|FACTURA|RECHNUNG|BILL|NOTA)\s*$",
            "", empresa, flags=re.IGNORECASE,
        ).strip()

    return empresa if empresa else None
