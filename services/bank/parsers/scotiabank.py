"""Scotiabank México statement parser (EXPERIMENTAL).

Date format: DD MMM (03 MAR) — year from header (Fechadecorte DD-MMM-YY).
Columns: Fecha Concepto Origen/Referencia Depósito Retiro Saldo
Multi-line transactions with contract/reference details.
Deposit vs retiro determined by balance comparison (saldo delta).
"""
from __future__ import annotations

EXPERIMENTAL = True

import logging
import re
from datetime import date
from decimal import Decimal
from typing import Any, Optional

from services.bank.parsers._base import MONTH_ABBR_ES, norm_text, parse_amount

logger = logging.getLogger(__name__)

_DATE_RE = re.compile(r"^(\d{2})\s+([A-Z]{3})\b")
_MONEY_RE = re.compile(r"\$([\d,]+\.\d{2})")


_DATE_NO_SPACE_RE = re.compile(r"^(\d{2})([A-Z]{3})\b")


def _extract_year(lines: list[tuple[int, int, str]]) -> Optional[int]:
    """Extract year from 'Fecha de corte DD-MMM-YY' or 'Periodo DD-MMM-YY/DD-MMM-YY'."""
    for _, _, text in lines[:30]:
        # Fechadecorte or Fecha de corte
        m = re.search(r"Fecha\s*de\s*corte\s+\d{2}-[A-Z]{3}-(\d{2})", text, re.IGNORECASE)
        if m:
            yy = int(m.group(1))
            return 2000 + yy if yy < 80 else 1900 + yy
        # Periodo DD-MMM-YY/DD-MMM-YY
        m = re.search(r"Periodo\s+\d{2}-[A-Z]{3}-(\d{2})\s*/\s*\d{2}-[A-Z]{3}-(\d{2})", text, re.IGNORECASE)
        if m:
            yy = int(m.group(2))
            return 2000 + yy if yy < 80 else 1900 + yy
    return None


def parse_scotiabank(pdf_path: str) -> list[dict[str, Any]]:
    """Parse Scotiabank bank statement PDF."""
    from services.bank.parsers._base import extract_text_per_line
    lines = extract_text_per_line(pdf_path)
    if not lines:
        logger.warning("Scotiabank parser: no text extracted from %s", pdf_path)
        return []

    year = _extract_year(lines)

    movements: list[dict[str, Any]] = []
    current: Optional[dict] = None
    in_movements = False
    movements_done = False  # Stop after first account
    prev_saldo: Optional[Decimal] = None

    # Extract opening balance from summary
    for _, _, text in lines:
        t = norm_text(text)
        if "SALDO INICIAL" in t or "SALDOINICIAL" in t:
            amounts = _MONEY_RE.findall(text)
            if amounts:
                prev_saldo = parse_amount(amounts[0])
            break

    for _, _, text in lines:
        text_stripped = text.strip()
        if not text_stripped:
            continue

        t_norm = norm_text(text_stripped)

        # Detect movement section (only first account)
        if "DETALLEDETUSMOVIMIENTOS" in t_norm.replace(" ", "") or \
           ("FECHA" in t_norm and "CONCEPTO" in t_norm and ("DEPOSITO" in t_norm or "RETIRO" in t_norm)):
            if not movements_done:
                in_movements = True
            continue

        if not in_movements:
            continue

        # End markers
        if _is_end_marker(t_norm):
            if current:
                _finalize_movement(current, prev_saldo)
                if current.get("saldo"):
                    prev_saldo = current["saldo"]
                movements.append(current)
                current = None
            in_movements = False
            if movements:
                movements_done = True
            continue

        # Page header noise
        if _is_noise(t_norm):
            continue

        # Transaction start: DD MMM or DDMMM (no space)
        m = _DATE_RE.match(text_stripped) or _DATE_NO_SPACE_RE.match(text_stripped)
        if m:
            if current:
                _finalize_movement(current, prev_saldo)
                if current.get("saldo"):
                    prev_saldo = current["saldo"]
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

            rest = text_stripped[m.end():].strip()

            # Extract $ amounts from line
            amounts = _MONEY_RE.findall(rest)
            amounts_dec = [parse_amount(a) for a in amounts]
            amounts_dec = [a for a in amounts_dec if a is not None]

            # Remove amounts from description
            desc = rest
            for a in amounts:
                desc = desc.replace("$" + a, "", 1)
            desc = re.sub(r"\s+", " ", desc).strip()

            current = {
                "fecha": dt.isoformat() if dt else None,
                "descripcion": desc,
                "deposito": None,
                "retiro": None,
                "saldo": None,
                "referencia": None,
                "raw_line": text_stripped,
                "_amounts": amounts_dec,  # resolve later
            }
            continue

        if not current:
            continue

        # Continuation line
        if not _is_noise(t_norm):
            # Extract reference
            ref_match = re.search(r"(?:CONTRATO|NUM OP|FORMA DE PAGO)\s*:?\s*(\S+)", t_norm)
            if t_norm.startswith("CONTRATO"):
                ref_match = re.search(r"CONTRATO:\s*(\S+)", text_stripped)
                if ref_match and not current.get("referencia"):
                    current["referencia"] = ref_match.group(1)
            current["descripcion"] += " " + text_stripped
            current["raw_line"] += " | " + text_stripped

    if current:
        _finalize_movement(current, prev_saldo)
        if current.get("saldo"):
            prev_saldo = current["saldo"]
        movements.append(current)

    # Clean up internal fields
    for m in movements:
        m.pop("_amounts", None)

    logger.info("Scotiabank parser: %d movements from %s", len(movements), pdf_path)
    return movements


def _finalize_movement(mov: dict, prev_saldo: Optional[Decimal]) -> None:
    """Resolve amounts into deposito/retiro/saldo based on balance delta."""
    amounts = mov.get("_amounts", [])
    if not amounts:
        return

    if len(amounts) >= 2:
        # Last amount is saldo, first is the transaction amount
        mov["saldo"] = amounts[-1]
        amt = amounts[0]
    elif len(amounts) == 1:
        # Single amount — could be amount-only or saldo-only
        amt = amounts[0]
        # If we have prev_saldo, try to determine if this is the amount
        if prev_saldo is not None:
            mov["saldo"] = None  # no saldo available
        else:
            mov["saldo"] = None
    else:
        return

    if len(amounts) >= 2 and prev_saldo is not None:
        saldo = mov["saldo"]
        # Determine deposit vs retiro from balance change
        if saldo > prev_saldo:
            mov["deposito"] = amt
        else:
            mov["retiro"] = amt
    elif len(amounts) == 1 and prev_saldo is not None:
        # No saldo shown — use keyword heuristics
        if _is_likely_deposit(mov["descripcion"]):
            mov["deposito"] = amt
        else:
            mov["retiro"] = amt
    else:
        # No prev_saldo — use keyword heuristics
        if _is_likely_deposit(mov["descripcion"]):
            mov["deposito"] = amt
        else:
            mov["retiro"] = amt


def _is_likely_deposit(desc: str) -> bool:
    d = desc.upper()
    return any(kw in d for kw in [
        "EFECTIVO COBRANZA", "DEPOSITO", "ABONO", "DEP ",
        "PAGO DE SERVICIO", "RENDIMIENTO", "INTERESES",
        "TRANSFERENCIA RECIBIDA", "DEVOLUCION", "BONIFICACION",
    ])


def _is_end_marker(t_norm: str) -> bool:
    markers = [
        "LASTASASDEINTERES", "LAS TASAS DE INTERES",
        "ENELCASODEENVIO", "EN EL CASO DE ENVIO",
        "TOTAL DE COMISIONES",
        "TOTALDECOMISIONES",
        "ABREVIATURAS",
        "DATOS FISCALES",
        "DATOSFISCALES",
        "SELLO DIGITAL",
        "SELLODIGITAL",
        "CADENA ORIGINAL",
        "CADENAORIGINAL",
    ]
    compact = t_norm.replace(" ", "")
    return any(m.replace(" ", "") in compact for m in markers)


def _is_noise(t_norm: str) -> bool:
    noise = [
        "PAGINA", "CUENTA ",
        "SCOTIABANK", "INVERLAT",
        "DETALLEDETUSMOVIMIENTOS",
    ]
    compact = t_norm.replace(" ", "")
    if compact.startswith("PAGINA") or "PAGINA" in t_norm[:20]:
        return True
    if re.match(r"^\d{6}\s+PAGINA", t_norm):
        return True
    return any(n.replace(" ", "") in compact for n in noise[1:])
