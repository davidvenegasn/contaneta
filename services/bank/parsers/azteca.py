"""Banco Azteca statement parser (EXPERIMENTAL).

Date format: YYYY/MM/DD (full ISO dates).
Columns: FECHA OP | FECHA VAL | No MOV | COD | CONCEPTO | CARGO | ABONO | SALDO
Multi-line transactions with RECEPTOR/EMISOR/NOM BENEF/RASTREO/CONCEPTO details.
Balance-delta method for cargo/abono classification.
"""
from __future__ import annotations

EXPERIMENTAL = True

import logging
import re
from datetime import date
from decimal import Decimal
from typing import Any, Optional

import pdfplumber

from services.bank.parsers._base import norm_text, parse_amount

logger = logging.getLogger(__name__)

_DATE_RE = re.compile(r"^(\d{4}/\d{2}/\d{2})\s+\d{4}/\d{2}/\d{2}\s+(.+)$")
_AMOUNT_RE = re.compile(r"[\d,]*\.\d{2}")


def _norm_amount(s: str) -> str:
    """Normalize amount strings like '.01' to '0.01'."""
    return "0" + s if s.startswith(".") else s


def parse_azteca(pdf_path: str) -> list[dict[str, Any]]:
    """Parse Banco Azteca bank statement PDF."""
    movements: list[dict[str, Any]] = []
    current: Optional[dict] = None
    in_movements = False
    movements_done = False
    prev_saldo: Optional[Decimal] = None

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            for line_text in text.split("\n"):
                line_stripped = line_text.strip()
                if not line_stripped:
                    continue

                t_norm = norm_text(line_stripped)

                # Detect movement section header
                if "DETALLE DE MOVIMIENTOS" in t_norm:
                    if not movements_done:
                        in_movements = True
                    continue

                # Page footer — pause movements parsing (don't flush current)
                if "LINEA AZTECA" in t_norm:
                    in_movements = False
                    continue

                # Column header
                if in_movements and "FECHA" in t_norm and "CONCEPTO" in t_norm and ("CARGO" in t_norm or "ABONO" in t_norm):
                    continue

                if not in_movements:
                    continue

                if _is_noise(t_norm):
                    continue

                # Transaction start: YYYY/MM/DD YYYY/MM/DD ...
                m = _DATE_RE.match(line_stripped)
                if m:
                    if current:
                        movements.append(current)

                    date_str = m.group(1)
                    rest = m.group(2).strip()

                    # Parse operation date
                    dt = None
                    try:
                        parts = date_str.split("/")
                        dt = date(int(parts[0]), int(parts[1]), int(parts[2]))
                    except (ValueError, IndexError):
                        pass

                    # SALDO INICIAL — track saldo, not a movement
                    if "SALDO INICIAL" in rest.upper():
                        if movements:
                            # Second account — stop parsing
                            current = None
                            in_movements = False
                            movements_done = True
                            continue
                        amounts = _AMOUNT_RE.findall(rest)
                        if amounts:
                            prev_saldo = parse_amount(_norm_amount(amounts[-1]))
                        current = None
                        continue

                    # Extract amounts
                    amounts = _AMOUNT_RE.findall(rest)
                    amounts_dec = [parse_amount(_norm_amount(a)) for a in amounts]
                    amounts_dec = [a for a in amounts_dec if a is not None]

                    # Remove amounts from description
                    desc = rest
                    for a in amounts:
                        desc = desc.replace(a, "", 1)
                    desc = re.sub(r"\s+", " ", desc).strip()
                    # Strip mov number and code prefix (e.g. "251 880 ")
                    desc = re.sub(r"^\d+\s+\d+\s+", "", desc)

                    deposito = None
                    retiro = None
                    saldo = None

                    if len(amounts_dec) >= 2:
                        saldo = amounts_dec[-1]
                        amt = amounts_dec[-2]
                        # Balance-delta classification
                        if prev_saldo is not None:
                            if saldo > prev_saldo:
                                deposito = amt
                            else:
                                retiro = amt
                        else:
                            if _is_deposit_keyword(desc):
                                deposito = amt
                            else:
                                retiro = amt
                        prev_saldo = saldo
                    elif len(amounts_dec) == 1:
                        saldo = amounts_dec[0]
                        prev_saldo = saldo

                    current = {
                        "fecha": dt.isoformat() if dt else None,
                        "descripcion": desc,
                        "deposito": deposito,
                        "retiro": retiro,
                        "saldo": saldo,
                        "referencia": None,
                        "raw_line": line_stripped,
                    }
                    continue

                if not current:
                    continue

                # Continuation line — capture reference, append to raw_line
                ref_match = re.search(r"RASTREO:\s*(\S+)", line_stripped)
                if ref_match and not current.get("referencia"):
                    current["referencia"] = ref_match.group(1)
                current["raw_line"] += " | " + line_stripped

    if current:
        movements.append(current)

    logger.info("Azteca parser: %d movements from %s", len(movements), pdf_path)
    return movements


def _is_deposit_keyword(desc: str) -> bool:
    d = desc.upper()
    return any(kw in d for kw in [
        "ABONO", "DEPOSITO", "INTERESES", "A SU FAVOR",
        "COMPLEMENTO INTS",
    ])


def _is_noise(t_norm: str) -> bool:
    return any(n in t_norm for n in [
        "PAG.", "________________",
        "OPERACION VALOR OPE",
    ])
