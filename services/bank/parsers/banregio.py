"""Banregio statement parser (EXPERIMENTAL).

Date format: DD only (day number) — month/year from period header.
Columns: DIA CONCEPTO CARGOS ABONOS SALDO
Single-line transactions. Multi-account statements (parses first account only).
Uses word x-positions to classify amounts into CARGOS/ABONOS/SALDO columns.
"""
from __future__ import annotations

EXPERIMENTAL = True

import logging
import re
from datetime import date
from decimal import Decimal
from typing import Any, Optional

import pdfplumber

from services.bank.parsers._base import MONTH_FULL_ES, norm_text, parse_amount

logger = logging.getLogger(__name__)

_DAY_RE = re.compile(r"^(\d{1,2})\s+(\S.*)$")
_AMOUNT_RE = re.compile(r"[\d,]+\.\d{2}")

# Column x-position thresholds for Banregio format
# Headers: CARGOS ~366, ABONOS ~443, SALDO ~527
# Amounts: CARGOS ~370-405, ABONOS ~460-483, SALDO ~520-560
_ABONOS_MIN_X = 430
_SALDO_MIN_X = 510


def _extract_month_year(lines: list) -> tuple[Optional[int], Optional[int]]:
    """Extract month and year from 'del DD al DD de MONTH YYYY'."""
    for text in lines:
        m = re.search(r"del\s+\d+\s+al\s+\d+\s+de\s+(\w+)\s+(\d{4})", text, re.IGNORECASE)
        if m:
            month_name = m.group(1).upper()
            year = int(m.group(2))
            month = MONTH_FULL_ES.get(month_name)
            return month, year
    return None, None


def parse_banregio(pdf_path: str) -> list[dict[str, Any]]:
    """Parse Banregio bank statement PDF."""
    movements: list[dict[str, Any]] = []
    in_movements = False
    movements_done = False
    month: Optional[int] = None
    year: Optional[int] = None

    with pdfplumber.open(pdf_path) as pdf:
        # Extract month/year from first page text
        first_text = pdf.pages[0].extract_text() or ""
        month, year = _extract_month_year(first_text.split("\n"))

        for page in pdf.pages:
            text = page.extract_text() or ""
            words = page.extract_words()

            for line_text in text.split("\n"):
                line_stripped = line_text.strip()
                if not line_stripped:
                    continue

                t_norm = norm_text(line_stripped)

                # Detect movement section header
                if "DIA" in t_norm and "CONCEPTO" in t_norm and ("CARGO" in t_norm or "ABONO" in t_norm):
                    if not movements_done:
                        in_movements = True
                    continue

                if not in_movements:
                    continue

                # Skip noise
                if _is_noise(t_norm):
                    continue

                # End markers
                if _is_end_marker(t_norm):
                    in_movements = False
                    if movements:
                        movements_done = True
                    continue

                # Transaction: starts with day number
                m_day = _DAY_RE.match(line_stripped)
                if m_day:
                    day = int(m_day.group(1))
                    if day < 1 or day > 31:
                        continue

                    rest = m_day.group(2)
                    dt = None
                    if month and year:
                        try:
                            dt = date(year, month, day)
                        except ValueError:
                            pass

                    # Find amounts and classify by position
                    deposito = None
                    retiro = None
                    saldo = None

                    # Find amount words on this line
                    amt_strs = _AMOUNT_RE.findall(rest)
                    for amt_str in amt_strs:
                        # Find x-position
                        col = _find_amount_column(words, amt_str)
                        val = parse_amount(amt_str)
                        if val is None:
                            continue
                        if col == "cargos" and retiro is None:
                            retiro = val
                        elif col == "abonos" and deposito is None:
                            deposito = val
                        elif col == "saldo":
                            saldo = val

                    # Remove amounts from description
                    desc = rest
                    for a in amt_strs:
                        desc = desc.replace(a, "", 1)
                    desc = re.sub(r"\s+", " ", desc).strip()

                    movements.append({
                        "fecha": dt.isoformat() if dt else None,
                        "descripcion": desc,
                        "deposito": deposito,
                        "retiro": retiro,
                        "saldo": saldo,
                        "referencia": None,
                        "raw_line": line_stripped,
                    })

    logger.info("Banregio parser: %d movements from %s", len(movements), pdf_path)
    return movements


def _find_amount_column(words: list, amt_str: str) -> str:
    """Classify amount into cargos/abonos/saldo by x-position."""
    clean = amt_str.replace(",", "")
    for w in words:
        if w["text"].replace(",", "") == clean or w["text"] == amt_str:
            x = w["x0"]
            if x < _ABONOS_MIN_X:
                return "cargos"
            elif x < _SALDO_MIN_X:
                return "abonos"
            else:
                return "saldo"
    return "cargos"  # fallback


def _is_end_marker(t_norm: str) -> bool:
    return any(m in t_norm for m in [
        "TOTAL", "TASA BRUTA", "SALDO MINIMO",
        "GRAFICO", "ESTE DOCUMENTO",
        "FOLIO FISCAL", "SELLO DIGITAL",
    ])


def _is_noise(t_norm: str) -> bool:
    return any(n in t_norm for n in [
        "PAGINA", "PAGE", "BANCO REGIONAL",
        "BANREGIO", "MUNICIPIO DE",
        "SALDO INICIAL",
    ])
