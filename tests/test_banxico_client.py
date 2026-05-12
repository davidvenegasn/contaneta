"""Tests for Banxico DOF exchange rate client."""
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

ISSUER_ID = 77777


@pytest.fixture(scope="module", autouse=True)
def _isolated_db():
    """Use a fresh temp DB for this module."""
    fd, db_path = tempfile.mkstemp(suffix=".db", prefix="test_banxico_")
    os.close(fd)

    import database
    old_path = database.DB_PATH
    database.DB_PATH = db_path

    # Create dof_rates table
    conn = database.db()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS dof_rates (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              date TEXT NOT NULL,
              currency TEXT NOT NULL,
              rate_to_mxn REAL NOT NULL,
              source TEXT NOT NULL DEFAULT 'banxico_dof',
              series TEXT,
              fetched_at TEXT NOT NULL DEFAULT (datetime('now')),
              UNIQUE(date, currency)
            );
        """)
    finally:
        conn.close()

    yield

    database.DB_PATH = old_path
    try:
        os.unlink(db_path)
    except OSError:
        pass


MOCK_BANXICO_RESPONSE = {
    "bmx": {
        "series": [{
            "idSerie": "SF43718",
            "titulo": "Tipo de cambio pesos por dólar E.U.A. Tipo de cambio para solventar obligaciones denominadas en moneda extranjera Fecha de determinación (FIX)",
            "datos": [
                {"fecha": "07/04/2026", "dato": "20.1234"},
                {"fecha": "08/04/2026", "dato": "20.2345"},
                {"fecha": "09/04/2026", "dato": "20.3456"},
            ],
        }],
    },
}


class TestGetRateMXN:
    def test_mxn_returns_one(self):
        from services.invoices.banxico_client import get_rate
        assert get_rate("2026-04-10", "MXN") == 1.0

    def test_mxn_case_insensitive(self):
        from services.invoices.banxico_client import get_rate
        assert get_rate("2026-04-10", "mxn") == 1.0


class TestBanxicoResponseParsing:
    @patch("services.invoices.banxico_client.os.getenv")
    @patch("services.invoices.banxico_client.urllib.request.urlopen")
    def test_parses_banxico_response(self, mock_urlopen, mock_getenv):
        mock_getenv.return_value = "fake-token"
        mock_resp = MagicMock()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.read.return_value = json.dumps(MOCK_BANXICO_RESPONSE).encode("utf-8")
        mock_urlopen.return_value = mock_resp

        from services.invoices.banxico_client import _fetch_from_banxico
        rate = _fetch_from_banxico("USD", "2026-04-09")
        assert rate == 20.3456

    @patch("services.invoices.banxico_client.os.getenv")
    @patch("services.invoices.banxico_client.urllib.request.urlopen")
    def test_picks_last_rate_before_date(self, mock_urlopen, mock_getenv):
        mock_getenv.return_value = "fake-token"
        mock_resp = MagicMock()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.read.return_value = json.dumps(MOCK_BANXICO_RESPONSE).encode("utf-8")
        mock_urlopen.return_value = mock_resp

        from services.invoices.banxico_client import _fetch_from_banxico
        # Ask for April 8 — should get rate from April 8 (20.2345)
        rate = _fetch_from_banxico("USD", "2026-04-08")
        assert rate == 20.2345

    @patch("services.invoices.banxico_client.os.getenv")
    def test_no_token_returns_none(self, mock_getenv):
        mock_getenv.return_value = ""
        from services.invoices.banxico_client import _fetch_from_banxico
        assert _fetch_from_banxico("USD", "2026-04-10") is None


class TestCacheBehavior:
    def test_cache_hit(self):
        from database import db_execute
        from services.invoices.banxico_client import get_rate
        # Pre-populate cache
        db_execute(
            "INSERT OR IGNORE INTO dof_rates (date, currency, rate_to_mxn, source, series) "
            "VALUES (?, ?, ?, ?, ?)",
            ("2026-03-15", "EUR", 22.5678, "banxico_dof", "SF46410"),
        )
        rate = get_rate("2026-03-15", "EUR")
        assert rate == 22.5678

    def test_fallback_to_nearest_cached(self):
        from database import db_execute
        from services.invoices.banxico_client import get_rate
        # Pre-populate cache for a Friday
        db_execute(
            "INSERT OR IGNORE INTO dof_rates (date, currency, rate_to_mxn, source, series) "
            "VALUES (?, ?, ?, ?, ?)",
            ("2026-03-20", "GBP", 25.1234, "banxico_dof", "SF60632"),
        )
        # Ask for Saturday — no API token set, should fallback to cached Friday
        rate = get_rate("2026-03-21", "GBP")
        assert rate == 25.1234


class TestUnsupportedCurrency:
    @patch("services.invoices.banxico_client.os.getenv")
    def test_unknown_currency_returns_none(self, mock_getenv):
        mock_getenv.return_value = "fake-token"
        from services.invoices.banxico_client import _fetch_from_banxico
        assert _fetch_from_banxico("XYZ", "2026-04-10") is None
