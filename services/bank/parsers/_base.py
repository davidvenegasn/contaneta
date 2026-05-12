"""Shared utilities for per-bank statement parsers."""
from __future__ import annotations

import logging
import re
import unicodedata
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Optional

logger = logging.getLogger(__name__)

MONTH_ABBR_ES = {
    "ENE": 1, "FEB": 2, "MAR": 3, "ABR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AGO": 8, "SEP": 9, "SET": 9, "OCT": 10, "NOV": 11, "DIC": 12,
}

MONTH_FULL_ES = {
    "ENERO": 1, "FEBRERO": 2, "MARZO": 3, "ABRIL": 4, "MAYO": 5, "JUNIO": 6,
    "JULIO": 7, "AGOSTO": 8, "SEPTIEMBRE": 9, "OCTUBRE": 10, "NOVIEMBRE": 11, "DICIEMBRE": 12,
}

_AMOUNT_RE = re.compile(r"-?\d{1,3}(?:,\d{3})*\.\d{2}")


def strip_accents(s: str) -> str:
    """Remove accents/diacritics from string."""
    return "".join(ch for ch in unicodedata.normalize("NFKD", s or "") if not unicodedata.combining(ch))


def norm_text(s: str) -> str:
    """Normalize text: strip accents, uppercase, collapse whitespace."""
    t = strip_accents(str(s or ""))
    t = re.sub(r"\s+", " ", t).strip().upper()
    return t


def extract_text_per_line(pdf_path: str) -> list[tuple[int, int, str]]:
    """Extract text from PDF, line by line. Returns list of (page_no, line_no, text)."""
    import pdfplumber
    lines: list[tuple[int, int, str]] = []
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page_no, page in enumerate(pdf.pages, 1):
                text = page.extract_text() or ""
                for line_no, line in enumerate(text.split("\n"), 1):
                    lines.append((page_no, line_no, line))
    except Exception as e:
        logger.warning("extract_text_per_line failed for %s: %s", pdf_path, e)
    return lines


def extract_full_text(pdf_path: str) -> str:
    """Extract all text from PDF as single string."""
    import pdfplumber
    try:
        with pdfplumber.open(pdf_path) as pdf:
            pages = []
            for page in pdf.pages:
                pages.append(page.extract_text() or "")
            return "\n".join(pages)
    except Exception as e:
        logger.warning("extract_full_text failed for %s: %s", pdf_path, e)
        return ""


def parse_amount(text: str) -> Optional[Decimal]:
    """Parse a monetary amount from text. Returns Decimal or None.
    Handles formats: 1,234.56  -1,234.56  1234.56
    """
    if not text:
        return None
    t = str(text).strip().replace("$", "").replace(" ", "")
    m = _AMOUNT_RE.search(t)
    if not m:
        return None
    raw = m.group(0).replace(",", "")
    try:
        return Decimal(raw)
    except (InvalidOperation, ValueError):
        return None


def parse_date_es(text: str, year_hint: Optional[int] = None) -> Optional[date]:
    """Parse a date from Spanish text. Supports common formats:
    - DD-MMM-YY (01-ENE-26)
    - DD/MM/YYYY (01/01/2026)
    - DD/MM/YY (01/01/26)
    - DD-MM-YYYY
    - DD de MONTH YYYY (01 de enero 2024)
    """
    if not text:
        return None
    t = strip_accents(text.strip().upper())

    # DD-MMM-YY or DD-MMM-YYYY (Banorte style)
    m = re.match(r"(\d{1,2})[/\-]([A-Z]{3,})[/\-](\d{2,4})", t)
    if m:
        d = int(m.group(1))
        mon_str = m.group(2)[:3]
        y = int(m.group(3))
        mm = MONTH_ABBR_ES.get(mon_str) or MONTH_FULL_ES.get(m.group(2))
        if mm:
            yyyy = y if y >= 100 else 2000 + y
            try:
                return date(yyyy, mm, d)
            except ValueError:
                pass

    # DD/MM/YYYY or DD-MM-YYYY
    m = re.match(r"(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})", t)
    if m:
        d, mm, yyyy = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            return date(yyyy, mm, d)
        except ValueError:
            pass

    # DD/MM/YY
    m = re.match(r"(\d{1,2})[/\-](\d{1,2})[/\-](\d{2})\b", t)
    if m:
        d, mm, y2 = int(m.group(1)), int(m.group(2)), int(m.group(3))
        yyyy = 2000 + y2
        try:
            return date(yyyy, mm, d)
        except ValueError:
            pass

    # "DD de MONTH YYYY" or "DD de MONTH de YYYY"
    m = re.match(r"(\d{1,2})\s+DE\s+(\w+)\s+(?:DE\s+)?(\d{4})", t)
    if m:
        d = int(m.group(1))
        mon_str = m.group(2)
        yyyy = int(m.group(3))
        mm = MONTH_FULL_ES.get(mon_str) or MONTH_ABBR_ES.get(mon_str[:3])
        if mm:
            try:
                return date(yyyy, mm, d)
            except ValueError:
                pass

    # YYYY-MM-DD (ISO)
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", t)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass

    return None
