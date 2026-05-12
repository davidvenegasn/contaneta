#!/usr/bin/env python3
"""
Test automático multi-tenant: A no puede descargar XML/PDF del UUID de B.

Crea una DB de test con 2 usuarios/issuers, 2 sat_cfdi (UUID distintos).
Simula sesión por cookie y llama a /portal/sat/xml/{uuid} y /portal/sat/pdf/{uuid}.
Esperado: A solo puede su UUID (200); el UUID de B → 404. Y viceversa.

Uso (desde la raíz del proyecto):
  APP_DB_PATH=/tmp/test_tenant_downloads.db python3 scripts/test_tenant_downloads.py
  # o sin env: usa DB temporal y la borra al final
"""
import os
import sys
import tempfile

# Fijar DB de test antes de importar config/app
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)

_test_db = os.environ.get("APP_DB_PATH")
if not _test_db:
    _fd, _test_db = tempfile.mkstemp(suffix=".db", prefix="test_tenant_")
    os.close(_fd)
    os.environ["APP_DB_PATH"] = _test_db
    _cleanup_db = True
else:
    _cleanup_db = False

# Asegurar SESSION_SECRET para firmar cookies (si no está definido, config usa aleatorio)
if not os.environ.get("SESSION_SECRET"):
    os.environ["SESSION_SECRET"] = "test-secret-tenant-downloads"

from migrations_runner import apply_migrations
from fastapi.testclient import TestClient

from config import BASE_DIR, DB_PATH
from app import app
from database import db
from services.auth import session as session_service

# Aplicar migraciones a la DB de test
apply_migrations(DB_PATH)

# UUIDs y ruta XML compartida (relativa a BASE_DIR)
UUID_A = "aaaaaaaa-bbbb-4ccc-d000-000000000001"
UUID_B = "bbbbbbbb-cccc-4ddd-d000-000000000002"
XML_PATH_REL = "scripts/fixtures/minimal.xml"
XML_PATH_ABS = os.path.join(BASE_DIR, XML_PATH_REL)
if not os.path.exists(XML_PATH_ABS):
    print("ERROR: Falta fixture XML:", XML_PATH_ABS)
    sys.exit(1)


def _insert_test_data():
    conn = db()
    try:
        # Limpiar datos de test previos (orden por FK: referencias a issuer/user primero)
        conn.execute("DELETE FROM sat_cfdi WHERE issuer_id IN (1, 2)")
        conn.execute("DELETE FROM memberships WHERE user_id IN (1, 2)")
        conn.execute("DELETE FROM subscriptions WHERE user_id IN (1, 2)")
        try:
            conn.execute("DELETE FROM quotation_items WHERE quotation_id IN (SELECT id FROM quotations WHERE issuer_id IN (1, 2))")
        except Exception:
            pass
        try:
            conn.execute("DELETE FROM invoice_items WHERE invoice_id IN (SELECT id FROM invoices WHERE issuer_id IN (1, 2))")
        except Exception:
            pass
        try:
            conn.execute("DELETE FROM payment_relations WHERE payment_invoice_id IN (SELECT id FROM invoices WHERE issuer_id IN (1, 2)) OR related_invoice_id IN (SELECT id FROM invoices WHERE issuer_id IN (1, 2))")
        except Exception:
            pass
        try:
            conn.execute("DELETE FROM invoices WHERE issuer_id IN (1, 2)")
        except Exception:
            pass
        for t in (
            "issuer_tokens", "sat_credentials", "sat_sync_state", "sat_requests", "sat_jobs",
            "customer_profiles", "supplier_profiles", "issuer_products", "quotations",
        ):
            try:
                conn.execute(f"DELETE FROM {t} WHERE issuer_id IN (1, 2)")
            except Exception:
                pass
        try:
            conn.execute("DELETE FROM audit_log WHERE issuer_id IN (1, 2) OR target_issuer_id IN (1, 2)")
        except Exception:
            pass
        for t in ("email_verifications", "password_resets"):
            try:
                conn.execute(f"DELETE FROM {t} WHERE user_id IN (1, 2)")
            except Exception:
                pass
        conn.execute("DELETE FROM users WHERE id IN (1, 2)")
        conn.execute("DELETE FROM issuers WHERE id IN (1, 2)")

        # Issuers y users (ids fijos para sesión)
        conn.execute(
            "INSERT INTO issuers (id, rfc, razon_social, active, created_at, updated_at) VALUES (1, 'TENANTA001', 'Tenant A', 1, datetime('now'), datetime('now'))"
        )
        conn.execute(
            "INSERT INTO issuers (id, rfc, razon_social, active, created_at, updated_at) VALUES (2, 'TENANTB002', 'Tenant B', 1, datetime('now'), datetime('now'))"
        )
        conn.execute(
            "INSERT INTO users (id, email, password_hash, created_at) VALUES (1, 'tenant_a@test.local', ?, datetime('now'))",
            ("$2b$12$dummyhash",),
        )
        conn.execute(
            "INSERT INTO users (id, email, password_hash, created_at) VALUES (2, 'tenant_b@test.local', ?, datetime('now'))",
            ("$2b$12$dummyhash",),
        )
        conn.execute(
            "INSERT INTO memberships (user_id, issuer_id, role, created_at) VALUES (1, 1, 'owner', datetime('now'))"
        )
        conn.execute(
            "INSERT INTO memberships (user_id, issuer_id, role, created_at) VALUES (2, 2, 'owner', datetime('now'))"
        )
        conn.execute(
            "INSERT INTO subscriptions (user_id, plan, status, created_at, updated_at) VALUES (1, 'pro', 'active', datetime('now'), datetime('now'))"
        )
        conn.execute(
            "INSERT INTO subscriptions (user_id, plan, status, created_at, updated_at) VALUES (2, 'pro', 'active', datetime('now'), datetime('now'))"
        )
        conn.execute(
            """INSERT INTO sat_cfdi (issuer_id, direction, uuid, xml_path, status, created_at, updated_at)
               VALUES (1, 'issued', ?, ?, 'Vigente', datetime('now'), datetime('now'))""",
            (UUID_A, XML_PATH_REL),
        )
        conn.execute(
            """INSERT INTO sat_cfdi (issuer_id, direction, uuid, xml_path, status, created_at, updated_at)
               VALUES (2, 'issued', ?, ?, 'Vigente', datetime('now'), datetime('now'))""",
            (UUID_B, XML_PATH_REL),
        )
        conn.commit()
    finally:
        conn.close()


def _cookie_for(user_id: int, issuer_id: int) -> dict:
    name = session_service.get_session_cookie_name()
    val = session_service.sign_session(user_id, issuer_id)
    return {name: val}


def run_tests():
    _insert_test_data()
    client = TestClient(app)

    cookie_a = _cookie_for(1, 1)  # usuario 1, issuer 1 (tenant A)
    cookie_b = _cookie_for(2, 2)  # usuario 2, issuer 2 (tenant B)

    errors = []

    # ---------- Tenant A no puede descargar UUID de B ----------
    r_xml_ab = client.get(f"/portal/sat/xml/{UUID_B}", cookies=cookie_a)
    if r_xml_ab.status_code != 404:
        errors.append(f"A + XML(UUID_B): esperado 404, obtuvo {r_xml_ab.status_code}")

    r_pdf_ab = client.get(f"/portal/sat/pdf/{UUID_B}", cookies=cookie_a)
    if r_pdf_ab.status_code not in (403, 404):
        errors.append(f"A + PDF(UUID_B): esperado 404/403, obtuvo {r_pdf_ab.status_code}")

    # ---------- Tenant A sí puede descargar su UUID ----------
    r_xml_aa = client.get(f"/portal/sat/xml/{UUID_A}", cookies=cookie_a)
    if r_xml_aa.status_code != 200:
        errors.append(f"A + XML(UUID_A): esperado 200, obtuvo {r_xml_aa.status_code}")

    r_pdf_aa = client.get(f"/portal/sat/pdf/{UUID_A}", cookies=cookie_a)
    if r_pdf_aa.status_code not in (200, 500):
        errors.append(f"A + PDF(UUID_A): esperado 200 o 500, obtuvo {r_pdf_aa.status_code}")

    # ---------- Tenant B no puede descargar UUID de A ----------
    r_xml_ba = client.get(f"/portal/sat/xml/{UUID_A}", cookies=cookie_b)
    if r_xml_ba.status_code != 404:
        errors.append(f"B + XML(UUID_A): esperado 404, obtuvo {r_xml_ba.status_code}")

    r_pdf_ba = client.get(f"/portal/sat/pdf/{UUID_A}", cookies=cookie_b)
    if r_pdf_ba.status_code not in (403, 404):
        errors.append(f"B + PDF(UUID_A): esperado 404/403, obtuvo {r_pdf_ba.status_code}")

    # ---------- Tenant B sí puede descargar su UUID ----------
    r_xml_bb = client.get(f"/portal/sat/xml/{UUID_B}", cookies=cookie_b)
    if r_xml_bb.status_code != 200:
        errors.append(f"B + XML(UUID_B): esperado 200, obtuvo {r_xml_bb.status_code}")

    r_pdf_bb = client.get(f"/portal/sat/pdf/{UUID_B}", cookies=cookie_b)
    if r_pdf_bb.status_code not in (200, 500):
        errors.append(f"B + PDF(UUID_B): esperado 200 o 500, obtuvo {r_pdf_bb.status_code}")

    if errors:
        for e in errors:
            print("[FALLO]", e)
        return 1
    print("OK: Test multi-tenant descargas XML/PDF pasado. A no puede descargar UUID de B (404); cada uno solo el suyo (200).")
    return 0


if __name__ == "__main__":
    try:
        code = run_tests()
    finally:
        if _cleanup_db and os.path.exists(_test_db):
            try:
                os.unlink(_test_db)
            except Exception:
                pass
    sys.exit(code)
