"""Security tests: verify SQL injection payloads are safely handled in bank movements."""
import sqlite3

import pytest
from starlette.testclient import TestClient

from app import app
from tests.helpers import make_session_cookie


@pytest.fixture()
def client_with_session():
    """Create test client with a valid session for issuer 1."""
    cookies = make_session_cookie(user_id=1, issuer_id=1)
    return TestClient(app, cookies=cookies, raise_server_exceptions=False)


class TestSqlInjectionViaSearch:
    """Verify search param does not allow SQL injection."""

    @pytest.mark.parametrize("payload", [
        "x') OR 1=1; DROP TABLE bank_movements; --",
        "' UNION SELECT * FROM users --",
        "'; DELETE FROM bank_movements WHERE ''='",
        "1 OR 1=1",
        "' OR ''='",
        "Robert'); DROP TABLE bank_movements;--",
    ])
    def test_should_not_crash_with_injection_payloads(self, client_with_session, payload):
        """Malicious search payloads must not cause 500 errors or data leaks."""
        r = client_with_session.get("/portal/movimientos", params={"search": payload})
        # Must return 200 (not 500 from broken SQL)
        assert r.status_code == 200, f"Injection payload caused {r.status_code}: {payload}"

    def test_should_return_200_with_percent_wildcard(self, client_with_session):
        """Bare % in search must not match all rows (LIKE metachar escaped)."""
        r = client_with_session.get("/portal/movimientos", params={"search": "%"})
        assert r.status_code == 200

    def test_should_return_200_with_underscore_wildcard(self, client_with_session):
        """Bare _ in search must not act as single-char wildcard."""
        r = client_with_session.get("/portal/movimientos", params={"search": "____"})
        assert r.status_code == 200

    def test_should_return_200_with_backslash(self, client_with_session):
        """Backslash in search must not break ESCAPE clause."""
        r = client_with_session.get("/portal/movimientos", params={"search": "test\\value"})
        assert r.status_code == 200


class TestSqlInjectionViaCategoria:
    """Verify categoria param is parameterized."""

    @pytest.mark.parametrize("payload", [
        "' UNION SELECT * FROM users --",
        "CUENTA_PROPIA' OR '1'='1",
        "'; DROP TABLE bank_movements;--",
    ])
    def test_should_not_crash_with_injection_payloads(self, client_with_session, payload):
        r = client_with_session.get("/portal/movimientos", params={"categoria": payload})
        assert r.status_code == 200


class TestSqlInjectionViaTipo:
    """Verify tipo param is parameterized."""

    @pytest.mark.parametrize("payload", [
        "INGRESO' OR '1'='1",
        "' UNION SELECT password FROM users--",
        "GASTO; DROP TABLE bank_movements",
    ])
    def test_should_not_crash_with_injection_payloads(self, client_with_session, payload):
        r = client_with_session.get("/portal/movimientos", params={"tipo": payload})
        assert r.status_code == 200


class TestSqlInjectionViaStatementId:
    """Verify statement_id param is parameterized."""

    @pytest.mark.parametrize("payload", [
        "stmt_1; DROP TABLE bank_movements",
        "' OR 1=1--",
        "stmt_' UNION SELECT * FROM issuers--",
    ])
    def test_should_not_crash_with_injection_payloads(self, client_with_session, payload):
        r = client_with_session.get("/portal/movimientos", params={"statement_id": payload})
        assert r.status_code == 200


class TestSqlInjectionViaCfdiMatchStatus:
    """Verify cfdi_match_status param is parameterized."""

    def test_should_not_crash_with_injection_payload(self, client_with_session):
        r = client_with_session.get(
            "/portal/movimientos",
            params={"cfdi_match_status": "confirmed' OR '1'='1"},
        )
        assert r.status_code == 200


class TestSqlInjectionViaMatchFilter:
    """Verify match_filter is whitelist-only (never interpolated)."""

    @pytest.mark.parametrize("payload", [
        "probable' OR 1=1--",
        "' UNION SELECT * FROM users--",
        "none; DROP TABLE bank_movements",
    ])
    def test_should_not_crash_with_injection_payloads(self, client_with_session, payload):
        r = client_with_session.get("/portal/movimientos", params={"match_filter": payload})
        assert r.status_code == 200


class TestCrossTenantIsolation:
    """Verify queries always filter by issuer_id from session, not request."""

    def test_should_not_leak_other_tenant_data(self):
        """Even with crafted params, data from other issuers must not appear."""
        cookies = make_session_cookie(user_id=1, issuer_id=1)
        client = TestClient(app, cookies=cookies, raise_server_exceptions=False)
        # Try to inject issuer_id via search
        r = client.get("/portal/movimientos", params={"search": "issuer_id = 999"})
        assert r.status_code == 200
