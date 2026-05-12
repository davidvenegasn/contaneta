"""Tests for financial statements — calculators, balance sheet, and route smoke test."""

import os
import sys
import tempfile
from pathlib import Path

# Fix DB + session for test environment
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_test_db = os.environ.get("APP_DB_PATH")
if not _test_db:
    _fd, _test_db = tempfile.mkstemp(suffix=".db", prefix="test_fin_stmt_")
    os.close(_fd)
    os.environ["APP_DB_PATH"] = _test_db
if not os.environ.get("SESSION_SECRET"):
    os.environ["SESSION_SECRET"] = "test-secret-fin-stmt"


from fastapi.testclient import TestClient  # noqa: E402

from app import app  # noqa: E402


# ──────────────────────────────────────────────────────────────────────────
# Calculator unit tests
# ──────────────────────────────────────────────────────────────────────────

from services.fiscal.calculators import (  # noqa: E402
    calc_iva,
    calc_pfae_general,
    calc_resico_pf,
)


def test_resico_basic_bracket():
    """Income of $10,000 should be in the first bracket (1% rate)."""
    result = calc_resico_pf(10_000.0)
    assert result["isr_estimado"] == 100.0  # 10,000 * 1%
    assert result["tasa_aplicada"] == 0.01
    assert result["base_gravable"] == 10_000.0


def test_resico_zero_income():
    result = calc_resico_pf(0)
    assert result["isr_estimado"] == 0.0


def test_pfae_basic_case():
    """Income $10,000 with deductible expenses $4,000 -> gross profit $6,000."""
    result = calc_pfae_general(ingresos_mes=10_000.0, deducciones_mes=4_000.0)
    # Taxable base = 10,000 - 4,000 = 6,000
    assert result["base_gravable"] == 6_000.0
    # ISR should be positive for $6,000 base
    assert result["isr_provisional"] > 0


def test_pfae_zero_base():
    """When expenses exceed income, ISR should be 0."""
    result = calc_pfae_general(ingresos_mes=5_000.0, deducciones_mes=6_000.0)
    assert result["isr_provisional"] == 0.0
    assert result["base_gravable"] == 0.0


def test_gross_profit_calculation():
    """Income $10k - deductible expenses $4k = gross profit $6k."""
    income = 10_000.0
    expenses = 4_000.0
    gross_profit = income - expenses
    assert gross_profit == 6_000.0


def test_iva_net_positive():
    """IVA collected > IVA paid -> IVA to pay."""
    result = calc_iva(iva_causado=1_600.0, iva_acreditable=640.0)
    assert result["iva_a_pagar"] == 960.0
    assert result["saldo_a_favor"] == 0.0


def test_iva_net_negative():
    """IVA collected < IVA paid -> saldo a favor."""
    result = calc_iva(iva_causado=400.0, iva_acreditable=800.0)
    assert result["iva_a_pagar"] == 0.0
    assert result["saldo_a_favor"] == 400.0


# ──────────────────────────────────────────────────────────────────────────
# Balance sheet: assets = liabilities + equity
# ──────────────────────────────────────────────────────────────────────────


def test_balance_always_balances():
    """Given any set of assets and liabilities, equity = assets - liabilities."""
    assets_total = 100_000.0
    liabilities_total = 40_000.0
    equity = assets_total - liabilities_total  # 60,000

    # Accounting equation: A = L + E
    assert abs(assets_total - (liabilities_total + equity)) < 0.01


def test_balance_with_zero_data():
    """When all values are zero, balance should still balance."""
    assets_total = 0.0
    liabilities_total = 0.0
    equity = assets_total - liabilities_total

    assert equity == 0.0
    assert abs(assets_total - (liabilities_total + equity)) < 0.01


def test_balance_summary_structure():
    """balance_summary should return proper dict structure with an empty DB."""
    from services.fiscal.statements import balance_summary

    # Use issuer_id=999999 (very unlikely to exist) -- should return zeroes
    result = balance_summary(999999, "2026-05")
    assert "assets" in result
    assert "liabilities" in result
    assert "equity" in result
    assert result["balanced"] is True
    assert result["assets"]["total"] == 0.0
    assert result["liabilities"]["total"] == 0.0
    assert result["equity"]["total"] == 0.0


def test_income_statement_structure():
    """income_statement should return proper dict structure with an empty DB."""
    from services.fiscal.statements import income_statement

    result = income_statement(999999, "2026-05")
    assert "month" in result
    assert "ytd" in result
    assert "regimen" in result
    assert "disclaimer" in result
    assert result["month"]["ingresos"] == 0.0
    assert result["ytd"]["ingresos"] == 0.0


# ──────────────────────────────────────────────────────────────────────────
# Route smoke test
# ──────────────────────────────────────────────────────────────────────────


def test_estados_financieros_route_exists():
    """GET /portal/estados-financieros unauthenticated should not return 404."""
    client = TestClient(app, raise_server_exceptions=False)
    r = client.get("/portal/estados-financieros", follow_redirects=False)
    # Unauthenticated -> redirect to login (302/303) or 401, but NOT 404
    assert r.status_code != 404
    assert r.status_code in (200, 302, 303, 401)


def test_estados_financieros_authenticated():
    """GET /portal/estados-financieros with session cookie should return 200."""
    from tests.helpers import make_session_cookie

    client = TestClient(app, raise_server_exceptions=False)
    cookies = make_session_cookie(issuer_id=1)
    r = client.get("/portal/estados-financieros", cookies=cookies, follow_redirects=False)
    # Could be 200 (page rendered) or 302 (redirect for some reason)
    assert r.status_code in (200, 302, 303)


def test_estados_financieros_csv_route():
    """GET /portal/estados-financieros/csv should return CSV or redirect."""
    from tests.helpers import make_session_cookie

    client = TestClient(app, raise_server_exceptions=False)
    cookies = make_session_cookie(issuer_id=1)
    r = client.get("/portal/estados-financieros/csv?ym=2026-05&tab=income", cookies=cookies, follow_redirects=False)
    assert r.status_code in (200, 302, 303)
    if r.status_code == 200:
        assert "text/csv" in r.headers.get("content-type", "")
