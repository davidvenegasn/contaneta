"""
Tests mínimos de aislamiento tenant (issuer A no puede ver recursos de issuer B).

Requiere pytest para ejecutarse:
  pytest tests/test_tenant_isolation.py
"""
import os
import sys
import tempfile
from pathlib import Path

import pytest

# Fijar DB de test antes de importar app/config
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_test_db = os.environ.get("APP_DB_PATH")
if not _test_db:
    _fd, _test_db = tempfile.mkstemp(suffix=".db", prefix="test_tenant_min_")
    os.close(_fd)
    os.environ["APP_DB_PATH"] = _test_db
if not os.environ.get("SESSION_SECRET"):
    os.environ["SESSION_SECRET"] = "test-secret-tenant-min"

from fastapi.testclient import TestClient  # noqa: E402

from config import DB_PATH  # noqa: E402
from database import db  # noqa: E402
from migrations_runner import apply_migrations  # noqa: E402
from tests.helpers import make_session_cookie  # noqa: E402

from app import app  # noqa: E402


ISSUER_A = 101
ISSUER_B = 102
USER_A = 101
USER_B = 102
QID_A = 11001
QID_B = 12001
JOB_A = 15001
JOB_B = 16001


def _seed_two_tenants():
    apply_migrations(DB_PATH)
    conn = db()
    try:
        # Limpiar solo nuestras fixtures (IDs altos para evitar colisiones con otros tests)
        conn.execute("DELETE FROM quotation_items WHERE quotation_id IN (?, ?)", (QID_A, QID_B))
        conn.execute("DELETE FROM quotations WHERE id IN (?, ?)", (QID_A, QID_B))
        conn.execute("DELETE FROM jobs WHERE id IN (?, ?)", (JOB_A, JOB_B))
        conn.execute("DELETE FROM memberships WHERE user_id IN (?, ?) OR issuer_id IN (?, ?)", (USER_A, USER_B, ISSUER_A, ISSUER_B))

        conn.execute(
            "INSERT OR IGNORE INTO issuers (id, rfc, razon_social, active, created_at, updated_at) VALUES (?, 'TENANTA101', 'A', 1, datetime('now'), datetime('now'))",
            (ISSUER_A,),
        )
        conn.execute(
            "INSERT OR IGNORE INTO issuers (id, rfc, razon_social, active, created_at, updated_at) VALUES (?, 'TENANTB102', 'B', 1, datetime('now'), datetime('now'))",
            (ISSUER_B,),
        )
        conn.execute(
            "INSERT OR IGNORE INTO users (id, email, password_hash, created_at) VALUES (?, 'a101@test.local', '$2b$12$x', datetime('now'))",
            (USER_A,),
        )
        conn.execute(
            "INSERT OR IGNORE INTO users (id, email, password_hash, created_at) VALUES (?, 'b102@test.local', '$2b$12$x', datetime('now'))",
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

        # Cotizaciones
        conn.execute(
            """
            INSERT INTO quotations (id, issuer_id, customer_rfc, customer_legal_name, status, public_token, created_at, updated_at)
            VALUES (?, ?, 'XAXX010101000', 'Cliente A', 'draft', 'tokA101', datetime('now'), datetime('now'))
            """,
            (QID_A, ISSUER_A),
        )
        conn.execute(
            """
            INSERT INTO quotations (id, issuer_id, customer_rfc, customer_legal_name, status, public_token, created_at, updated_at)
            VALUES (?, ?, 'XEXX010101000', 'Cliente B', 'draft', 'tokB102', datetime('now'), datetime('now'))
            """,
            (QID_B, ISSUER_B),
        )

        # Jobs
        conn.execute(
            """
            INSERT INTO jobs (id, issuer_id, name, status, progress, created_at, updated_at)
            VALUES (?, ?, 'test', 'queued', 0, datetime('now'), datetime('now'))
            """,
            (JOB_A, ISSUER_A),
        )
        conn.execute(
            """
            INSERT INTO jobs (id, issuer_id, name, status, progress, created_at, updated_at)
            VALUES (?, ?, 'test', 'queued', 0, datetime('now'), datetime('now'))
            """,
            (JOB_B, ISSUER_B),
        )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture(scope="module")
def client():
    _seed_two_tenants()
    return TestClient(app)


def test_tenant_a_cannot_get_quotation_of_b(client):
    cookie_a = make_session_cookie(issuer_id=ISSUER_A, user_id=USER_A)
    r = client.get(f"/api/quotations/{QID_B}", cookies=cookie_a)
    assert r.status_code == 404, f"Esperado 404, obtuvo {r.status_code}"


def test_tenant_b_cannot_get_quotation_of_a(client):
    cookie_b = make_session_cookie(issuer_id=ISSUER_B, user_id=USER_B)
    r = client.get(f"/api/quotations/{QID_A}", cookies=cookie_b)
    assert r.status_code == 404, f"Esperado 404, obtuvo {r.status_code}"


def test_tenant_a_cannot_get_job_of_b(client):
    cookie_a = make_session_cookie(issuer_id=ISSUER_A, user_id=USER_A)
    r = client.get(f"/api/jobs/{JOB_B}", cookies=cookie_a)
    assert r.status_code == 404, f"Esperado 404, obtuvo {r.status_code}"


def test_tenant_b_cannot_get_job_of_a(client):
    cookie_b = make_session_cookie(issuer_id=ISSUER_B, user_id=USER_B)
    r = client.get(f"/api/jobs/{JOB_A}", cookies=cookie_b)
    assert r.status_code == 404, f"Esperado 404, obtuvo {r.status_code}"

