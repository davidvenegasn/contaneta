"""Santander México statement parser (EXPERIMENTAL).

Date format: DD-MMM-YYYY (09-MAY-2024).
Columns: FECHA FOLIO DESCRIPCION DEPOSITO RETIRO SALDO
Multi-line transactions with SPEI details.
Handles doubled-character PDF artifacts (shadow text).
"""
from __future__ import annotations

EXPERIMENTAL = True

import logging
import re
from datetime import date
from decimal import Decimal
from typing import Any, Optional

from services.bank.parsers._base import MONTH_ABBR_ES, extract_text_per_line, norm_text, parse_amount

logger = logging.getLogger(__name__)

_DATE_RE = re.compile(r"^(\d{2})-([A-Z0-9]{3})-(\d{4})")
_AMOUNT_RE = re.compile(r"\d{1,3}(?:,\d{3})*\.\d{2}")

# OCR substitution map for month abbreviations (0→O, 1→I, etc.)
_OCR_MONTH_FIX = {
    "AG0": "AGO", "AGD": "AGO", "EN0": "ENO", "FE8": "FEB", "MA8": "MAR",
    "0CT": "OCT", "N0V": "NOV", "D1C": "DIC",
}


def _dedupe_shadow_lines(lines: list[tuple[int, int, str]]) -> list[tuple[int, int, str]]:
    """Remove doubled-character shadow lines (PDF rendering artifact).
    e.g., '0033--MMAARR--22002255' is the shadow of '03-MAR-2025'.
    Heuristic: if a line has many repeated adjacent characters, skip it.
    """
    result = []
    for page, line_no, text in lines:
        # Check for double-character pattern: each char appears twice consecutively
        if len(text) > 10:
            # Sample: take first 20 chars and check if adjacent pairs are equal
            sample = text[:min(20, len(text))]
            doubled = 0
            for i in range(0, len(sample) - 1, 2):
                if sample[i] == sample[i + 1]:
                    doubled += 1
            if doubled >= len(sample) // 3:
                continue  # Skip shadow line
        result.append((page, line_no, text))
    return result


def _extract_year_and_period(lines: list[tuple[int, int, str]]) -> Optional[int]:
    """Extract year from PERIODO DEL DD-MMM-YYYY AL DD-MMM-YYYY."""
    for _, _, text in lines[:30]:
        m = re.search(r"PERIODO\s+DEL\s+\d{2}-[A-Z]{3}-(\d{4})\s+AL\s+\d{2}-[A-Z]{3}-(\d{4})", text, re.IGNORECASE)
        if m:
            return int(m.group(2))
        m = re.search(r"CORTE\s+AL\s+\d{2}-[A-Z]{3}-(\d{4})", text, re.IGNORECASE)
        if m:
            return int(m.group(1))
    return None


def _extract_opening_balance(lines: list[tuple[int, int, str]]) -> Optional[Decimal]:
    """Extract opening balance from 'SALDO FINAL DEL PERIODO ANTERIOR: $X,XXX.XX'."""
    for _, _, text in lines:
        t = norm_text(text)
        if "SALDO FINAL DEL PERIODO ANTERIOR" in t or "SALDO INICIAL" in t:
            # Extract amount after the colon
            amt_text = text.split(":")[-1] if ":" in text else text
            amt = parse_amount(amt_text)
            if amt is not None:
                return amt
    return None


def parse_santander(pdf_path: str) -> list[dict[str, Any]]:
    """Parse Santander bank statement PDF."""
    lines = extract_text_per_line(pdf_path)
    if not lines:
        logger.warning("Santander parser: no text extracted from %s", pdf_path)
        return []

    lines = _dedupe_shadow_lines(lines)
    year = _extract_year_and_period(lines)

    movements: list[dict[str, Any]] = []
    in_movements = False
    current_movement: Optional[dict] = None

    for page_no, line_no, text in lines:
        text_stripped = text.strip()
        if not text_stripped:
            continue

        t_norm = norm_text(text_stripped)

        # Detect movement section
        if "DETALLE DE MOVIMIENTOS" in t_norm:
            in_movements = True
            continue

        if "SALDO FINAL DEL PERIODO ANTERIOR" in t_norm:
            in_movements = True
            continue

        # Table header (normal or spaced-out "F E C H A")
        if in_movements and ("FECHA" in t_norm or "F E C H A" in t_norm) and ("FOLIO" in t_norm or "F O L I O" in t_norm):
            if current_movement:
                movements.append(current_movement)
                current_movement = None
            continue

        # End markers — stop collecting continuation lines after footer
        if in_movements and ("TOTAL DE MOVIMIENTOS" in t_norm or "RESUMEN DE MOVIMIENTOS" in t_norm or
                             "PAGINA" in t_norm or "SANTANDER" == t_norm.strip() or
                             re.match(r"^TOTAL\s+[\d,]+", t_norm)):
            if current_movement:
                movements.append(current_movement)
                current_movement = None
            continue

        if not in_movements:
            continue

        # Skip noise
        if _is_noise(t_norm):
            continue

        # Try to parse as movement line
        m = _DATE_RE.match(text_stripped)
        if m:
            if current_movement:
                movements.append(current_movement)

            day = int(m.group(1))
            mon_str = m.group(2).upper()
            mon_str = _OCR_MONTH_FIX.get(mon_str, mon_str)  # Fix OCR artifacts
            y = int(m.group(3))
            month = MONTH_ABBR_ES.get(mon_str)
            dt = None
            if month:
                try:
                    dt = date(y, month, day)
                except ValueError:
                    pass

            rest = text_stripped[m.end():].strip()

            # Extract folio (number after date)
            folio = ""
            folio_match = re.match(r"(\d{4,})\s*", rest)
            if folio_match:
                folio = folio_match.group(1)
                rest = rest[folio_match.end():]

            # Extract amounts from end
            amounts = _AMOUNT_RE.findall(rest)
            amounts_dec = [parse_amount(a) for a in amounts]
            amounts_dec = [a for a in amounts_dec if a is not None]

            # Remove amounts from description
            desc = rest
            for a in amounts:
                desc = desc.replace(a, "", 1)
            desc = re.sub(r"\s+", " ", desc).strip()

            deposito = None
            retiro = None
            saldo = None

            if len(amounts_dec) == 3:
                # DEPOSITO RETIRO SALDO — one of dep/ret is the amount, the other is empty
                deposito = amounts_dec[0]
                saldo = amounts_dec[2]
            elif len(amounts_dec) == 2:
                # Amount + SALDO
                saldo = amounts_dec[-1]
                amt = amounts_dec[0]
                if _is_deposit(desc):
                    deposito = amt
                else:
                    retiro = amt
            elif len(amounts_dec) == 1:
                amt = amounts_dec[0]
                if _is_deposit(desc):
                    deposito = amt
                else:
                    retiro = amt

            current_movement = {
                "fecha": dt.isoformat() if dt else None,
                "descripcion": desc,
                "deposito": deposito,
                "retiro": retiro,
                "saldo": saldo,
                "referencia": folio or None,
                "raw_line": text_stripped,
            }
        elif current_movement:
            # Continuation line
            if not _is_noise(t_norm):
                # Check for reference info
                ref_match = re.search(r"(?:REF|REFERENCIA|CLAVE DE RASTREO)\s+(\S+)", t_norm)
                if ref_match and not current_movement.get("referencia"):
                    current_movement["referencia"] = ref_match.group(1)
                current_movement["descripcion"] += " " + text_stripped.strip()
                current_movement["raw_line"] += " | " + text_stripped.strip()

    if current_movement:
        movements.append(current_movement)

    logger.info("Santander parser: %d movements from %s", len(movements), pdf_path)
    return movements


def _is_deposit(desc: str) -> bool:
    d = desc.upper()
    return any(kw in d for kw in [
        "DEPOSITO", "ABONO", "INTERESES", "SPEI RECIBIDO",
        "TRANSFERENCIA RECIBIDA", "DEVOLUCION", "BONIFICACION",
    ])


def _is_noise(t_norm: str) -> bool:
    noise = [
        "BANCO SANTANDER", "INSTITUCION DE BANCA", "GRUPO FINANCIERO",
        "DATO NO VERIFICADO", "ESTADO DE CUENTA",
        "DINERO CRECIENTE", "INVERSION CRECIENTE",
        "SALDO PROMEDIO", "TASA BRUTA", "DIAS DEL PERIODO",
        "GAT NOMINAL", "GAT REAL",
        "RESUMEN INFORMATIVO", "RESUMEN INTERESES",
        "RESUMEN SALDOS", "GRAFICO",
        "TELEFONO", "SUCURSAL",
        "INFORMACION FISCAL", "SELLO DIGITAL", "CERTIFICADO DEL",
        "FOLIO INTERNO", "FECHA Y HORA DE", "REGIMEN FISCAL",
        "LUGAR DE EXPEDICION", "UNIDAD DE MEDIDA", "METODO DE PAGO",
        "TIPO DE COMPROBANTE", "CADENA ORIGINAL",
    ]
    return any(n in t_norm for n in noise)
