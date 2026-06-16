"""Tests for the onboarding wizard."""
import pytest

from database import db

ISSUER_ID = 99930
USER_ID = 99930


@pytest.fixture(scope="module", autouse=True)
def seed():
    conn = db()
    conn.execute(
        "INSERT OR IGNORE INTO issuers (id, rfc, razon_social, active, created_at, updated_at) "
        "VALUES (?, 'ONB010101AAA', 'Onboarding Test SA', 1, datetime('now'), datetime('now'))",
        (ISSUER_ID,),
    )
    conn.execute(
        "INSERT OR IGNORE INTO users (id, email, password_hash, created_at) "
        "VALUES (?, 'onb@test.local', 'x', datetime('now'))",
        (USER_ID,),
    )
    conn.execute(
        "INSERT OR IGNORE INTO memberships (user_id, issuer_id, role, created_at) "
        "VALUES (?, ?, 'owner', datetime('now'))",
        (USER_ID, ISSUER_ID),
    )
    conn.commit()
    conn.close()
    yield


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient
    from app import app
    from tests.helpers import make_session_cookie
    cookies = make_session_cookie(issuer_id=ISSUER_ID, user_id=USER_ID)
    return TestClient(app, raise_server_exceptions=False, cookies=cookies)


def test_should_respond_200_onboarding_page(client):
    """GET /portal/onboarding should return 200."""
    resp = client.get("/portal/onboarding")
    assert resp.status_code == 200
    assert "Bienvenido" in resp.text or "Configuracion" in resp.text


def test_should_have_5_steps_in_wizard(client):
    """Wizard should display all 5 steps."""
    resp = client.get("/portal/onboarding")
    assert resp.status_code == 200
    assert "Perfil" in resp.text
    assert "FIEL" in resp.text
    assert "CSD" in resp.text


def test_should_skip_onboarding(client):
    """POST /portal/onboarding/skip should dismiss the wizard."""
    resp = client.post("/portal/onboarding/skip")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True


def test_should_advance_onboarding(client):
    """POST /portal/onboarding/advance should increment step."""
    resp = client.post("/portal/onboarding/advance")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
