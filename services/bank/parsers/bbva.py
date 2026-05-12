"""BBVA México statement parser (EXPERIMENTAL).

Supports BBVA Bancomer / BBVA México corporate and personal accounts.
Date format: DD/MMM (year inferred from header period).
Columns: FECHA OPER | FECHA LIQ | COD | DESCRIPCION | [REFERENCIA] | CARGOS | ABONOS | SALDO
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

# Movement line pattern: DD/MMM DD/MMM COD DESCRIPTION [amounts...]
_DATE_RE = re.compile(r"^(\d{1,2})/([A-Z]{3})\s+(\d{1,2})/([A-Z]{3})\s+")
# Continuation line (starts with "Ref." or indented text, no date)
_REF_RE = re.compile(r"^(?:Ref\.|REF\.?)\s*", re.IGNORECASE)
# Amount pattern
_AMOUNT_RE = re.compile(r"\d{1,3}(?:,\d{3})*\.\d{2}")


def _extract_year_from_header(lines: list[tuple[int, int, str]]) -> Optional[int]:
    """Extract statement year from 'Periodo DEL DD/MM/YYYY AL DD/MM/YYYY' header."""
    for _, _, text in lines[:30]:
        m = re.search(r"(?:Periodo|PERIODO)\s+DEL\s+\d{1,2}/\d{1,2}/(\d{4})\s+AL\s+\d{1,2}/\d{1,2}/(\d{4})", text, re.IGNORECASE)
        if m:
            return int(m.group(2))  # Use end-of-period year
        m = re.search(r"Fecha\s+de\s+Corte\s+\d{1,2}/\d{1,2}/(\d{4})", text, re.IGNORECASE)
        if m:
            return int(m.group(1))
    return None


def _extract_balances(lines: list[tuple[int, int, str]]) -> tuple[Optional[Decimal], Optional[Decimal]]:
    """Extract opening and closing balances from header."""
    opening = None
    closing = None
    for _, _, text in lines[:40]:
        t = norm_text(text)
        if "LIQUIDACION INICIAL" in t or "OPERACION INICIAL" in t:
            amt = parse_amount(text.split("Inicial")[-1] if "Inicial" in text else text.split("INICIAL")[-1])
            if amt is not None and opening is None:
                opening = amt
        if "SALDO FINAL" in t:
            amt = parse_amount(text.split("Final")[-1] if "Final" in text else text.split("FINAL")[-1])
            if amt is not None:
                closing = amt
    return opening, closing


def _is_table_header(text: str) -> bool:
    """Check if line is the column header row."""
    t = norm_text(text)
    return ("FECHA" in t and ("CARGOS" in t or "ABONOS" in t or "SALDO" in t)) or \
           ("OPER" in t and "LIQ" in t and "COD" in t and "DESCRIPCION" in t)


def _is_noise_line(text: str) -> bool:
    """Filter out non-movement noise lines."""
    t = norm_text(text)
    if not t:
        return True
    noise_markers = [
        "ESTADO DE CUENTA", "PAGINA", "NO. DE CUENTA", "NO. DE CLIENTE",
        "ESTIMADO CLIENTE", "BANCOMER", "BBVA MEXICO", "BBVA BANCOMER",
        "PASEO DE LA REFORMA", "CON BANCOMER", "ADELANTE",
        "INFORMACION FINANCIERA", "RENDIMIENTO", "SALDO PROMEDIO",
        "TASA BRUTA", "INTERESES A FAVOR", "ISR RETENIDO",
        "COMISIONES DE LA CUENTA", "TOTAL COMISIONES",
        "OTROS PRODUCTOS", "CONTRATO PRODUCTO", "GAT NOMINAL",
        "DETALLE DE MOVIMIENTOS", "TOTAL DE MOVIMIENTOS",
        "TOTAL IMPORTE CARGOS", "TOTAL IMPORTE ABONOS",
        "MANEJO DE CUENTA", "ANUALIDAD", "OPERACIONES",
        "CARGOS OBJETADOS", "ABONOS OBJETADOS",
        "SU ESTADO DE CUENTA", "TAMBIEN LE INFORMAMOS",
        "EL CUAL PUEDE", "CHEQUES PAGADOS",
        "FECHA DE CORTE", "PERIODO DEL",
    ]
    for marker in noise_markers:
        if marker in t:
            return True
    # Page number lines like "1/7"
    if re.match(r"^\d+\s*/\s*\d+\s*$", t.strip()):
        return True
    return False


def _parse_date(day: int, month_abbr: str, year: int) -> Optional[date]:
    """Parse a BBVA date from day/month_abbr components."""
    month = MONTH_ABBR_ES.get(month_abbr.upper())
    if not month:
        return None
    try:
        return date(year, month, day)
    except ValueError:
        return None


def parse_bbva(pdf_path: str) -> list[dict[str, Any]]:
    """Parse BBVA bank statement PDF into list of movement dicts."""
    lines = extract_text_per_line(pdf_path)
    if not lines:
        logger.warning("BBVA parser: no text extracted from %s", pdf_path)
        return []

    year = _extract_year_from_header(lines) or 2025
    opening, closing = _extract_balances(lines)

    # Find movement section
    movements: list[dict[str, Any]] = []
    in_movements = False
    current_movement: Optional[dict] = None

    for page_no, line_no, text in lines:
        text_stripped = text.strip()
        if not text_stripped:
            continue

        t_norm = norm_text(text_stripped)

        # Detect movement section start
        if "DETALLE DE MOVIMIENTOS" in t_norm:
            in_movements = True
            continue

        # Detect movement section end
        if "TOTAL DE MOVIMIENTOS" in t_norm or "TOTAL IMPORTE CARGOS" in t_norm:
            if current_movement:
                movements.append(current_movement)
                current_movement = None
            in_movements = False
            continue

        if not in_movements:
            continue

        # Skip headers and noise
        if _is_table_header(text_stripped) or _is_noise_line(text_stripped):
            continue

        # Try to parse as a new movement line (starts with DD/MMM DD/MMM)
        m = _DATE_RE.match(text_stripped)
        if m:
            # Save previous movement
            if current_movement:
                movements.append(current_movement)

            day_oper = int(m.group(1))
            mon_oper = m.group(2)
            dt = _parse_date(day_oper, mon_oper, year)

            rest = text_stripped[m.end():].strip()
            # Extract code (usually 3 chars like C19, S39, etc.)
            code_match = re.match(r"([A-Z]\d{2})\s+", rest)
            code = ""
            if code_match:
                code = code_match.group(1)
                rest = rest[code_match.end():]

            # Extract amounts from the end of the line
            amounts = _AMOUNT_RE.findall(rest)
            amounts_decimal = []
            for a in amounts:
                val = parse_amount(a)
                if val is not None:
                    amounts_decimal.append(val)

            # Remove amounts from description
            desc = rest
            for a in amounts:
                desc = desc.replace(a, "", 1)
            desc = re.sub(r"\s+", " ", desc).strip()

            # Determine cargo (withdrawal) vs abono (deposit)
            # BBVA format: DESCRIPCION [REFERENCIA] CARGOS ABONOS [SALDO_OPER SALDO_LIQ]
            # With 1 amount: it's either cargo or abono (position determines)
            # We'll use keyword heuristics and balance comparison
            cargo = None
            abono = None
            saldo = None

            if len(amounts_decimal) >= 3:
                # Likely: amount, saldo_oper, saldo_liq (or cargo, abono, saldo...)
                # Take first as the movement amount, last as balance
                saldo = amounts_decimal[-1]
                # Determine if first amount is cargo or abono
                amt = amounts_decimal[0]
                if _is_likely_deposit(desc, code):
                    abono = amt
                else:
                    cargo = amt
            elif len(amounts_decimal) == 2:
                # Usually: amount + saldo
                saldo = amounts_decimal[-1]
                amt = amounts_decimal[0]
                if _is_likely_deposit(desc, code):
                    abono = amt
                else:
                    cargo = amt
            elif len(amounts_decimal) == 1:
                amt = amounts_decimal[0]
                if _is_likely_deposit(desc, code):
                    abono = amt
                else:
                    cargo = amt

            current_movement = {
                "fecha": dt.isoformat() if dt else None,
                "descripcion": desc,
                "deposito": abono,
                "retiro": cargo,
                "saldo": saldo,
                "referencia": None,
                "raw_line": text_stripped,
                "code": code,
            }
        elif current_movement:
            # Continuation line — append to description
            if _REF_RE.match(text_stripped):
                ref_text = _REF_RE.sub("", text_stripped).strip()
                if current_movement.get("referencia"):
                    current_movement["referencia"] += " " + ref_text
                else:
                    current_movement["referencia"] = ref_text
                current_movement["descripcion"] += " " + ref_text
            elif not _is_noise_line(text_stripped):
                # Could have additional amounts
                extra_amounts = _AMOUNT_RE.findall(text_stripped)
                if not extra_amounts:
                    current_movement["descripcion"] += " " + text_stripped
                current_movement["raw_line"] += " | " + text_stripped

    # Don't forget last movement
    if current_movement:
        movements.append(current_movement)

    logger.info("BBVA parser: %d movements from %s (year=%d)", len(movements), pdf_path, year)
    return movements


def _is_likely_deposit(desc: str, code: str) -> bool:
    """Heuristic: is this amount likely a deposit/abono?"""
    d = desc.upper()
    deposit_keywords = ["DEPOSITO", "ABONO", "INTERESES GANADOS", "SPEI RECIBIDO",
                        "TRANSFERENCIA RECIBIDA", "TRASPASO RECIBIDO", "NOMINA",
                        "DEVOLUCION", "BONIFICACION"]
    for kw in deposit_keywords:
        if kw in d:
            return True
    # Code hints: some BBVA codes indicate deposits
    if code and code.startswith("C") and "INTERESES" in d:
        return True
    return False
