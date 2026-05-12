from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_test_db = os.environ.get("APP_DB_PATH")
if not _test_db:
    _fd, _test_db = tempfile.mkstemp(suffix=".db", prefix="test_bank_parser_")
    os.close(_fd)
    os.environ["APP_DB_PATH"] = _test_db
if not os.environ.get("SESSION_SECRET"):
    os.environ["SESSION_SECRET"] = "test-secret-bank-parser"

from services.bank.bank_parse_preview import parse_bank_pdf_to_movements_preview  # noqa: E402


def test_bank_parser_preview_handles_missing_file():
    r = parse_bank_pdf_to_movements_preview("/tmp/__nonexistent_bank_statement__.pdf")
    assert isinstance(r, dict)
    assert "movements" in r and isinstance(r["movements"], list)
    assert "summary" in r and isinstance(r["summary"], dict)
    assert r["summary"].get("error") == "file_not_found"

