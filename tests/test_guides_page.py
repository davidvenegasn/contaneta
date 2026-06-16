"""Tests for the guides / help center page (Phase 8)."""

import pytest

from database import db

ISSUER_ID = 99908
USER_ID = 99908


@pytest.fixture(scope="module", autouse=True)
def seed():
    """Create test data for guides tests."""
    conn = db()
    conn.execute(
        """INSERT OR IGNORE INTO issuers (id, rfc, razon_social, active, regimen_fiscal)
           VALUES (?, 'XGUIDE010AAA', 'Guide Test SA', 1, '601')""",
        (ISSUER_ID,),
    )
    conn.execute(
        """INSERT OR IGNORE INTO users (id, email, password_hash)
           VALUES (?, 'guide@test.com', 'x')""",
        (USER_ID,),
    )
    conn.execute(
        """INSERT OR IGNORE INTO memberships (user_id, issuer_id, role)
           VALUES (?, ?, 'owner')""",
        (USER_ID, ISSUER_ID),
    )
    conn.commit()
    conn.close()
    yield


def _client():
    from fastapi.testclient import TestClient

    from app import app
    from tests.helpers import make_session_cookie

    c = TestClient(app)
    cookies = make_session_cookie(ISSUER_ID, USER_ID)
    for k, v in cookies.items():
        c.cookies.set(k, v)
    return c


def test_guides_page_returns_200():
    """GET /portal/guides should return 200."""
    c = _client()
    resp = c.get("/portal/guides")
    assert resp.status_code == 200


def test_guides_page_has_search():
    """Guides page should have a search input."""
    c = _client()
    resp = c.get("/portal/guides")
    assert 'id="guidesSearch"' in resp.text


def test_guides_page_has_glossary():
    """Guides page should include the glossary section."""
    c = _client()
    resp = c.get("/portal/guides")
    assert "Glosario fiscal" in resp.text
    assert "CFDI" in resp.text
    assert "FIEL" in resp.text


def test_guides_page_has_nota_credito():
    """Guides page should include nota de crédito guide."""
    c = _client()
    resp = c.get("/portal/guides")
    assert "Nota de cr" in resp.text


def test_guides_page_has_extranjero():
    """Guides page should include facturar a extranjero guide."""
    c = _client()
    resp = c.get("/portal/guides")
    assert "cliente extranjero" in resp.text


def test_facturas_page_has_help_link():
    """Facturas hub should have a contextual help link."""
    c = _client()
    resp = c.get("/portal/facturas")
    assert "help-link" in resp.text


def test_quotations_page_has_help_link():
    """Quotations page should have a contextual help link."""
    c = _client()
    resp = c.get("/portal/cotizaciones")
    assert "help-link" in resp.text
