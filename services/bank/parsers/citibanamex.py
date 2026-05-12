"""Citibanamex statement parser (EXPERIMENTAL).

Date format: DD MMM (05 ABR) — year from header.
Columns: FECHA CONCEPTO RETIROS DEPOSITOS SALDO
Multi-line transactions: description → CAJA → HORA (amounts).
Uses word x-positions to classify amounts into RETIROS/DEPOSITOS/SALDO columns.
"""
from __future__ import annotations

EXPERIMENTAL = True

import logging
import re
from datetime import date
from decimal import Decimal
from typing import Any, Optional

import pdfplumber

from services.bank.parsers._base import MONTH_ABBR_ES, norm_text, parse_amount

logger = logging.getLogger(__name__)

_DATE_RE = re.compile(r"^(\d{2})\s+([A-Z]{3})\b")
_HORA_RE = re.compile(r"^HORA\s+\d{2}:\d{2}")
_CAJA_RE = re.compile(r"^CAJA\s+\d+\s+AUT")
_AMOUNT_RE = re.compile(r"\d{1,3}(?:,\d{3})*\.\d{2}")

# Column x-position thresholds (consistent across all sample PDFs)
_RETIROS_MAX_X = 330
_DEPOSITOS_MAX_X = 415


def _extract_lines_with_amounts(pdf_path: str) -> list[dict]:
    """Extract text lines with positional amount classification.

    Returns list of dicts: {page, line_no, text, amounts: [{value, column}]}
    where column is 'retiros', 'depositos', or 'saldo'.
    """
    result = []
    with pdfplumber.open(pdf_path) as pdf:
        for page_idx, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            words = page.extract_words()
            text_lines = text.split("\n")

            for line_no, line_text in enumerate(text_lines):
                if not line_text.strip():
                    continue

                # Find amounts in this line and classify by x-position
                line_amounts = []
                if _HORA_RE.match(line_text.strip()):
                    # For HORA lines, find amount words and classify by position
                    # Group words by y-position to find this line's words
                    amount_strs = _AMOUNT_RE.findall(line_text)
                    for amt_str in amount_strs:
                        # Find this amount's word in the page words
                        col = _classify_amount_position(words, amt_str, line_text, text_lines, line_no)
                        amt_val = parse_amount(amt_str)
                        if amt_val is not None:
                            line_amounts.append({"value": amt_val, "column": col, "raw": amt_str})

                result.append({
                    "page": page_idx + 1,
                    "line_no": line_no + 1,
                    "text": line_text.strip(),
                    "amounts": line_amounts,
                })
    return result


def _classify_amount_position(words: list, amt_str: str, line_text: str, all_lines: list, line_idx: int) -> str:
    """Classify an amount into retiros/depositos/saldo based on x-position."""
    # Find candidate word matches for this amount
    clean_amt = amt_str.replace(",", "")
    for w in words:
        w_clean = w["text"].replace(",", "")
        if w_clean == clean_amt or w["text"] == amt_str:
            x = w["x0"]
            if x < _RETIROS_MAX_X:
                return "retiros"
            elif x < _DEPOSITOS_MAX_X:
                return "depositos"
            else:
                return "saldo"
    # Fallback: if amount is very large relative to position in line, assume saldo
    return "depositos"


def _extract_year(lines: list[dict]) -> Optional[int]:
    """Extract year from 'ESTADO DE CUENTA AL DD DE MONTH DE YYYY'."""
    for entry in lines[:10]:
        m = re.search(r"ESTADO DE CUENTA AL\s+\d+\s+DE\s+\w+\s+DE\s+(\d{4})", entry["text"], re.IGNORECASE)
        if m:
            return int(m.group(1))
    return None


def _extract_period_month(lines: list[dict]) -> Optional[int]:
    """Extract month from 'RESUMEN DEL: DD/MMM/YYYY AL DD/MMM/YYYY'."""
    for entry in lines[:50]:
        m = re.search(r"RESUMEN DEL:\s*\d{2}/([A-Z]{3})/\d{4}", entry["text"], re.IGNORECASE)
        if m:
            mon = MONTH_ABBR_ES.get(m.group(1).upper())
            return mon
    return None


def parse_citibanamex(pdf_path: str) -> list[dict[str, Any]]:
    """Parse Citibanamex bank statement PDF."""
    lines = _extract_lines_with_amounts(pdf_path)
    if not lines:
        logger.warning("Citibanamex parser: no text extracted from %s", pdf_path)
        return []

    year = _extract_year(lines)
    period_month = _extract_period_month(lines)

    movements: list[dict[str, Any]] = []
    current: Optional[dict] = None
    in_movements = False
    movements_done = False  # Stop after first account

    for entry in lines:
        text = entry["text"]
        t_norm = norm_text(text)

        # Detect movement section (only first account)
        if "DETALLE DE OPERACIONES" in t_norm:
            if not movements_done:
                in_movements = True
            continue

        if "SALDO ANTERIOR" in t_norm and in_movements:
            # Extract opening balance
            amounts = _AMOUNT_RE.findall(text)
            continue

        # Table header
        if "FECHA" in t_norm and "CONCEPTO" in t_norm and ("RETIROS" in t_norm or "DEPOSITOS" in t_norm):
            continue

        # End markers
        if in_movements and _is_end_marker(t_norm):
            if current:
                movements.append(current)
                current = None
            in_movements = False
            if movements:
                movements_done = True
            continue

        # Page header noise
        if _is_page_header(t_norm):
            continue

        if not in_movements:
            continue

        # Skip noise lines
        if _is_noise(t_norm):
            continue

        # Transaction start: DD MMM
        m = _DATE_RE.match(text)
        if m:
            if current:
                movements.append(current)

            day = int(m.group(1))
            mon_str = m.group(2).upper()
            month = MONTH_ABBR_ES.get(mon_str)
            dt = None
            if month and year:
                try:
                    dt = date(year, month, day)
                except ValueError:
                    pass

            desc = text[m.end():].strip()

            current = {
                "fecha": dt.isoformat() if dt else None,
                "descripcion": desc,
                "deposito": None,
                "retiro": None,
                "saldo": None,
                "referencia": None,
                "raw_line": text,
            }
            continue

        if not current:
            continue

        # CAJA line — extract authorization
        if _CAJA_RE.match(text):
            aut_match = re.search(r"AUT\s+(\d+)", text)
            if aut_match and aut_match.group(1) != "00000000":
                current["referencia"] = aut_match.group(1)
            continue

        # HORA line — extract amounts
        if _HORA_RE.match(text):
            for amt_info in entry["amounts"]:
                col = amt_info["column"]
                val = amt_info["value"]
                if col == "retiros" and current["retiro"] is None:
                    current["retiro"] = val
                elif col == "depositos" and current["deposito"] is None:
                    current["deposito"] = val
                elif col == "saldo":
                    current["saldo"] = val
            continue

        # Continuation line — append to description
        if not _is_noise(t_norm):
            current["descripcion"] += " " + text
            current["raw_line"] += " | " + text

    if current:
        movements.append(current)

    logger.info("Citibanamex parser: %d movements from %s", len(movements), pdf_path)
    return movements


def _is_end_marker(t_norm: str) -> bool:
    markers = [
        "SALDO MINIMO REQUERIDO",
        "COMISIONES COBRADAS EN EL PERIODO",
        "CADENA ORIGINAL",
        "SELLO DIGITAL",
        "ESTE DOCUMENTO ES UNA REPRESENTACION",
        "TOTAL DE IMPUESTOS",
        "SUBTOTALES",
    ]
    return any(m in t_norm for m in markers)


def _is_page_header(t_norm: str) -> bool:
    headers = [
        "ESTADO DE CUENTA AL",
        "CLIENTE:",
        "PAGINA:",
    ]
    return any(t_norm.startswith(h) or h in t_norm for h in headers)


def _is_noise(t_norm: str) -> bool:
    noise = [
        "BANCO NACIONAL DE MEXICO", "CITIBANAMEX", "GRUPO FINANCIERO",
        "CONDUSEF", "CITISERVICE", "RFC:BNM",
        "IPAB GARANTIZA", "PROTECCION DE DATOS",
        "AGRADECEMOS SU PREFERENCIA",
        "IMPORTANTE:", "ACLARACION SOBRE",
        "COMISIONES CON FINES INFORMATIVOS",
        "LEY FEDERAL",
    ]
    return any(n in t_norm for n in noise)
