"""Registry for per-bank statement parsers."""
from __future__ import annotations

import logging
import os
from typing import Any, Callable

logger = logging.getLogger(__name__)


class BankParserNotReady(Exception):
    """Raised when a parser exists but is EXPERIMENTAL and not allowed in current environment."""
    pass


# Registry: bank_name -> (parser_function, is_experimental)
BANK_PARSERS: dict[str, tuple[Callable, bool]] = {}


def register_parser(bank_name: str, parser_fn: Callable, experimental: bool = True) -> None:
    """Register a parser function for a bank."""
    BANK_PARSERS[bank_name.upper()] = (parser_fn, experimental)


def parse_statement(bank_name: str, pdf_path: str) -> list[dict[str, Any]]:
    """Dispatch to the correct parser for the given bank.
    Raises BankParserNotReady if parser is experimental and env is not dev.
    Raises KeyError if no parser registered for bank.
    """
    key = bank_name.upper()
    if key not in BANK_PARSERS:
        raise KeyError(f"No parser registered for bank: {bank_name}")
    parser_fn, is_experimental = BANK_PARSERS[key]
    if is_experimental:
        env = os.environ.get("ENV", "dev")
        dev_mode = os.environ.get("DEV_MODE", "1")
        if env == "prod" and dev_mode != "1":
            raise BankParserNotReady(f"Parser for {bank_name} is EXPERIMENTAL. Not available in production.")
        logger.warning("Using EXPERIMENTAL parser for bank: %s", bank_name)
    return parser_fn(pdf_path)


def _register_builtin_parsers() -> None:
    """Register all built-in parsers."""
    try:
        from services.bank.parsers.bbva import EXPERIMENTAL as bbva_exp
        from services.bank.parsers.bbva import parse_bbva
        register_parser("BBVA", parse_bbva, experimental=bbva_exp)
    except ImportError:
        pass
    try:
        from services.bank.parsers.santander import EXPERIMENTAL as santander_exp
        from services.bank.parsers.santander import parse_santander
        register_parser("SANTANDER", parse_santander, experimental=santander_exp)
    except ImportError:
        pass
    try:
        from services.bank.parsers.citibanamex import EXPERIMENTAL as citi_exp
        from services.bank.parsers.citibanamex import parse_citibanamex
        register_parser("CITIBANAMEX", parse_citibanamex, experimental=citi_exp)
    except ImportError:
        pass
    try:
        from services.bank.parsers.scotiabank import EXPERIMENTAL as scotia_exp
        from services.bank.parsers.scotiabank import parse_scotiabank
        register_parser("SCOTIABANK", parse_scotiabank, experimental=scotia_exp)
    except ImportError:
        pass
    try:
        from services.bank.parsers.banbajio import EXPERIMENTAL as bajio_exp
        from services.bank.parsers.banbajio import parse_banbajio
        register_parser("BANBAJIO", parse_banbajio, experimental=bajio_exp)
    except ImportError:
        pass


_register_builtin_parsers()


def list_parsers() -> dict[str, dict[str, Any]]:
    """Return info about all registered parsers."""
    return {
        name: {"experimental": exp, "parser": fn.__module__ + "." + fn.__name__}
        for name, (fn, exp) in BANK_PARSERS.items()
    }
