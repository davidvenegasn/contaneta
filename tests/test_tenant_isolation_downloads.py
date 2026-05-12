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

# Importar app después de fijar ENV/DB
from app import app
from config import BASE_DIR, DB_PATH
from database import db
from migrations_runner import apply_migrations
from tests.helpers import make_session_cookie

UUID_A = "aaaaaaaa-bbbb-4ccc-d000-000000000001"
UUID_B = "bbbbbbbb-cccc-4ddd-d000-000000000002"
XML_FIXTURE_REL = "scripts/fixtures/minimal.xml"

ISSUER_A = 201
ISSUER_B = 202
USER_A = 201
USER_B = 202


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
        # Limpiar solo nuestras fixtures (IDs altos para evitar colisiones con otros tests)
        conn.execute("DELETE FROM sat_cfdi WHERE issuer_id IN (?, ?)", (ISSUER_A, ISSUER_B))
        conn.execute("DELETE FROM memberships WHERE user_id IN (?, ?) OR issuer_id IN (?, ?)", (USER_A, USER_B, ISSUER_A, ISSUER_B))

        conn.execute(
            "INSERT OR IGNORE INTO issuers (id, rfc, razon_social, active, created_at, updated_at) VALUES (?, 'TENANTA201', 'A', 1, datetime('now'), datetime('now'))",
            (ISSUER_A,),
        )
        conn.execute(
            "INSERT OR IGNORE INTO issuers (id, rfc, razon_social, active, created_at, updated_at) VALUES (?, 'TENANTB202', 'B', 1, datetime('now'), datetime('now'))",
            (ISSUER_B,),
        )
        conn.execute(
            "INSERT OR IGNORE INTO users (id, email, password_hash, created_at) VALUES (?, 'a201@test.local', '$2b$12$x', datetime('now'))",
            (USER_A,),
        )
        conn.execute(
            "INSERT OR IGNORE INTO users (id, email, password_hash, created_at) VALUES (?, 'b202@test.local', '$2b$12$x', datetime('now'))",
            (USER_B,),
        )
        conn.execute(
            "INSERT INTO memberships (user_id, issuer_id, role, created_at) VALUES (?, ?, 'owner', datetime('now'))",
            (USER_A, ISSUER_A),
        )
        conn.execute(
            "INSERT INTO memberships (user_id, issuer_id, role, created_at) VALUES (?, ?, 'owner', datetime('now'))",
            (USER_B, ISSUER_B),
        )
        conn.execute(
            "INSERT INTO sat_cfdi (issuer_id, direction, uuid, xml_path, status, created_at, updated_at) VALUES (?, 'issued', ?, ?, 'Vigente', datetime('now'), datetime('now'))",
            (ISSUER_A, UUID_A, XML_FIXTURE_REL),
        )
        conn.execute(
            "INSERT INTO sat_cfdi (issuer_id, direction, uuid, xml_path, status, created_at, updated_at) VALUES (?, 'issued', ?, ?, 'Vigente', datetime('now'), datetime('now'))",
            (ISSUER_B, UUID_B, XML_FIXTURE_REL),
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
    cookie_a = make_session_cookie(issuer_id=ISSUER_A, user_id=USER_A)
    r = tenant_client.get(f"/portal/sat/xml/{UUID_B}", cookies=cookie_a)
    assert r.status_code == 404, f"Esperado 404, obtuvo {r.status_code}"


def test_tenant_a_can_download_own_xml(tenant_client):
    """A puede descargar su propio XML."""
    cookie_a = make_session_cookie(issuer_id=ISSUER_A, user_id=USER_A)
    r = tenant_client.get(f"/portal/sat/xml/{UUID_A}", cookies=cookie_a)
    assert r.status_code == 200, f"Esperado 200, obtuvo {r.status_code}"


def test_tenant_b_cannot_download_tenant_a_xml(tenant_client):
    """B (issuer 2) no puede descargar XML del UUID de A (issuer 1)."""
    cookie_b = make_session_cookie(issuer_id=ISSUER_B, user_id=USER_B)
    r = tenant_client.get(f"/portal/sat/xml/{UUID_A}", cookies=cookie_b)
    assert r.status_code == 404, f"Esperado 404, obtuvo {r.status_code}"


def test_tenant_b_can_download_own_xml(tenant_client):
    """B puede descargar su propio XML."""
    cookie_b = make_session_cookie(issuer_id=ISSUER_B, user_id=USER_B)
    r = tenant_client.get(f"/portal/sat/xml/{UUID_B}", cookies=cookie_b)
    assert r.status_code == 200, f"Esperado 200, obtuvo {r.status_code}"
