"""BanBajío statement parser (EXPERIMENTAL).

Date format: DD MMM (30 ABR) — year from PERIODO header.
Columns: FECHA DESCRIPCION DE LA OPERACION DEPOSITOS RETIROS SALDO
Multi-line transactions with NO. REF. / DOCTO.
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

_DATE_RE = re.compile(r"^(\d{1,2})\s+([A-Z]{3})\b")
_MONEY_RE = re.compile(r"\$\s*([\d,]+\.\d{2})")


def _extract_year(lines: list[tuple[int, int, str]]) -> Optional[int]:
    """Extract year from 'PERIODO: D DE MONTH AL D DE MONTH DE YYYY'."""
    for _, _, text in lines[:10]:
        m = re.search(r"DE\s+(\d{4})\s*$", text.strip())
        if m:
            return int(m.group(1))
        m = re.search(r"FECHA DE CORTE\s+\d+\s+\w+\s+(\d{4})", text, re.IGNORECASE)
        if m:
            return int(m.group(1))
    return None


def parse_banbajio(pdf_path: str) -> list[dict[str, Any]]:
    """Parse BanBajío bank statement PDF."""
    lines = extract_text_per_line(pdf_path)
    if not lines:
        logger.warning("BanBajío parser: no text extracted from %s", pdf_path)
        return []

    year = _extract_year(lines)

    movements: list[dict[str, Any]] = []
    current: Optional[dict] = None
    in_movements = False
    movements_done = False

    for _, _, text in lines:
        text_stripped = text.strip()
        if not text_stripped:
            continue

        t_norm = norm_text(text_stripped)

        # Detect movement section
        if "DETALLE DE LA CUENTA" in t_norm:
            if not movements_done:
                in_movements = True
            continue

        # Column header
        if in_movements and "FECHA" in t_norm and "DESCRIPCION" in t_norm and ("DEPOSITO" in t_norm or "RETIRO" in t_norm):
            continue

        # Skip DOCTO/REF header continuation
        if in_movements and t_norm in ("DOCTO", "NO. REF. /"):
            continue

        # Opening balance
        if in_movements and "SALDO INICIAL" in t_norm:
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

        if not in_movements:
            continue

        if _is_noise(t_norm):
            continue

        # Transaction start: DD MMM
        m = _DATE_RE.match(text_stripped)
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

            rest = text_stripped[m.end():].strip()

            # Extract $ amounts
            amounts = _MONEY_RE.findall(rest)
            amounts_dec = [parse_amount(a) for a in amounts]
            amounts_dec = [a for a in amounts_dec if a is not None]

            # Remove amounts from description
            desc = rest
            for a in amounts:
                desc = desc.replace("$" + a, "", 1).replace("$ " + a, "", 1)
            desc = re.sub(r"\s+", " ", desc).strip()

            deposito = None
            retiro = None
            saldo = None

            if len(amounts_dec) == 3:
                deposito = amounts_dec[0]
                retiro = amounts_dec[1]
                saldo = amounts_dec[2]
            elif len(amounts_dec) == 2:
                # Amount + saldo — determine by keyword
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

            current = {
                "fecha": dt.isoformat() if dt else None,
                "descripcion": desc,
                "deposito": deposito,
                "retiro": retiro,
                "saldo": saldo,
                "referencia": None,
                "raw_line": text_stripped,
            }
            continue

        if not current:
            continue

        # Continuation line
        if not _is_noise(t_norm):
            ref_match = re.search(r"(?:REF|REFERENCIA)\s*[.:]\s*(\S+)", t_norm)
            if ref_match and not current.get("referencia"):
                current["referencia"] = ref_match.group(1)
            current["descripcion"] += " " + text_stripped
            current["raw_line"] += " | " + text_stripped

    if current:
        movements.append(current)

    logger.info("BanBajío parser: %d movements from %s", len(movements), pdf_path)
    return movements


def _is_deposit(desc: str) -> bool:
    d = desc.upper()
    return any(kw in d for kw in [
        "DEPOSITO", "ABONO", "INTERESES", "DEP ", "RENDIMIENTO",
        "TRANSFERENCIA RECIBIDA", "DEVOLUCION", "BONIFICACION",
        "PAGO DE SERVICIO",
    ])


def _is_end_marker(t_norm: str) -> bool:
    return any(m in t_norm for m in [
        "SALDO TOTAL", "TOTAL DE MOVIMIENTOS",
        "ESTE DOCUMENTO ES UNA REPRESENTACION",
        "SELLO DIGITAL", "CADENA ORIGINAL",
        "RESUMEN DE COMISIONES",
        "CONTINUA EN LA SIGUIENTE PAGINA",
    ])


def _is_noise(t_norm: str) -> bool:
    return any(n in t_norm for n in [
        "PAGINA", "ESTADO DE CUENTA",
        "BANCO DEL BAJIO", "BANBAJIO",
        "NUMERO DE CLIENTE", "R.F.C.",
    ])
