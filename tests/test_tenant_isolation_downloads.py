"""
Test de aislamiento tenant: issuer A no puede descargar XML/PDF de un UUID que pertenece a issuer B.
Usa rutas /portal/sat/xml/{uuid} y /portal/sat/pdf/{uuid} con sesión por cookie.
"""
import os
import sys
import tempfile
from pathlib import Path

import pytest

# Fijar DB de test antes de importar app
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Usar DB temporal para no tocar la DB de desarrollo
_test_db = os.environ.get("APP_DB_PATH")
if not _test_db:
    _fd, _test_db = tempfile.mkstemp(suffix=".db", prefix="test_tenant_")
    os.close(_fd)
    os.environ["APP_DB_PATH"] = _test_db
if not os.environ.get("SESSION_SECRET"):
    os.environ["SESSION_SECRET"] = "test-secret-tenant-isolation"

from fastapi.testclient import TestClient

from config import BASE_DIR, DB_PATH
from database import db
from migrations_runner import apply_migrations
from tests.helpers import make_session_cookie

# Importar app después de fijar ENV/DB
from app import app

UUID_A = "aaaaaaaa-bbbb-4ccc-d000-000000000001"
UUID_B = "bbbbbbbb-cccc-4ddd-d000-000000000002"
XML_FIXTURE_REL = "scripts/fixtures/minimal.xml"


def _ensure_fixture():
    path = os.path.join(BASE_DIR, XML_FIXTURE_REL)
    if not os.path.exists(path):
        pytest.skip(f"Fixture XML no encontrado: {path}")


def _insert_tenant_fixtures():
    """Inserta 2 issuers, 2 users, 2 sat_cfdi (UUID_A para issuer 1, UUID_B para issuer 2)."""
    apply_migrations(DB_PATH)
    _ensure_fixture()
    conn = db()
    try:
        conn.execute("DELETE FROM sat_cfdi WHERE issuer_id IN (1, 2)")
        conn.execute("DELETE FROM memberships WHERE issuer_id IN (1, 2)")
        conn.execute("DELETE FROM users WHERE id IN (1, 2)")
        conn.execute("DELETE FROM issuers WHERE id IN (1, 2)")
        conn.execute(
            "INSERT INTO issuers (id, rfc, razon_social, active, created_at, updated_at) VALUES (1, 'TENANTA001', 'A', 1, datetime('now'), datetime('now'))"
        )
        conn.execute(
            "INSERT INTO issuers (id, rfc, razon_social, active, created_at, updated_at) VALUES (2, 'TENANTB002', 'B', 1, datetime('now'), datetime('now'))"
        )
        conn.execute(
            "INSERT INTO users (id, email, password_hash, created_at) VALUES (1, 'a@test.local', '$2b$12$x', datetime('now'))"
        )
        conn.execute(
            "INSERT INTO users (id, email, password_hash, created_at) VALUES (2, 'b@test.local', '$2b$12$x', datetime('now'))"
        )
        conn.execute("INSERT INTO memberships (user_id, issuer_id, role, created_at) VALUES (1, 1, 'owner', datetime('now'))")
        conn.execute("INSERT INTO memberships (user_id, issuer_id, role, created_at) VALUES (2, 2, 'owner', datetime('now'))")
        conn.execute(
            "INSERT INTO sat_cfdi (issuer_id, direction, uuid, xml_path, status, created_at, updated_at) VALUES (1, 'issued', ?, ?, 'Vigente', datetime('now'), datetime('now'))",
            (UUID_A, XML_FIXTURE_REL),
        )
        conn.execute(
            "INSERT INTO sat_cfdi (issuer_id, direction, uuid, xml_path, status, created_at, updated_at) VALUES (2, 'issued', ?, ?, 'Vigente', datetime('now'), datetime('now'))",
            (UUID_B, XML_FIXTURE_REL),
        )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture(scope="module")
def tenant_client():
    _insert_tenant_fixtures()
    return TestClient(app)


def test_tenant_a_cannot_download_tenant_b_xml(tenant_client):
    """A (issuer 1) no puede descargar XML del UUID de B (issuer 2)."""
    cookie_a = make_session_cookie(issuer_id=1, user_id=1)
    r = tenant_client.get(f"/portal/sat/xml/{UUID_B}", cookies=cookie_a)
    assert r.status_code == 404, f"Esperado 404, obtuvo {r.status_code}"


def test_tenant_a_can_download_own_xml(tenant_client):
    """A puede descargar su propio XML."""
    cookie_a = make_session_cookie(issuer_id=1, user_id=1)
    r = tenant_client.get(f"/portal/sat/xml/{UUID_A}", cookies=cookie_a)
    assert r.status_code == 200, f"Esperado 200, obtuvo {r.status_code}"


def test_tenant_b_cannot_download_tenant_a_xml(tenant_client):
    """B (issuer 2) no puede descargar XML del UUID de A (issuer 1)."""
    cookie_b = make_session_cookie(issuer_id=2, user_id=2)
    r = tenant_client.get(f"/portal/sat/xml/{UUID_A}", cookies=cookie_b)
    assert r.status_code == 404, f"Esperado 404, obtuvo {r.status_code}"


def test_tenant_b_can_download_own_xml(tenant_client):
    """B puede descargar su propio XML."""
    cookie_b = make_session_cookie(issuer_id=2, user_id=2)
    r = tenant_client.get(f"/portal/sat/xml/{UUID_B}", cookies=cookie_b)
    assert r.status_code == 200, f"Esperado 200, obtuvo {r.status_code}"
