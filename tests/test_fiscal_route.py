"""Smoke test for /portal/fiscal route."""
import sqlite3
import pytest

import database
from tests.helpers import make_session_cookie


@pytest.fixture()
def fiscal_db(tmp_path):
    """Create temp DB with required tables for fiscal route."""
    db_path = str(tmp_path / "test_fiscal.db")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS issuers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rfc TEXT NOT NULL DEFAULT 'TEST010101AAA',
            alias TEXT NOT NULL DEFAULT 'Test Co',
            nombre TEXT,
            razon_social TEXT,
            regimen_fiscal TEXT DEFAULT '612',
            active INTEGER NOT NULL DEFAULT 1,
            facturapi_org_id TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS memberships (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            issuer_id INTEGER NOT NULL,
            role TEXT NOT NULL DEFAULT 'owner'
        );
        CREATE TABLE IF NOT EXISTS sat_cfdi (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            issuer_id INTEGER NOT NULL,
            uuid TEXT,
            direction TEXT NOT NULL,
            fecha_emision TEXT,
            rfc_emisor TEXT,
            nombre_emisor TEXT,
            rfc_receptor TEXT,
            nombre_receptor TEXT,
            total REAL,
            subtotal REAL,
            moneda TEXT DEFAULT 'MXN',
            tipo_comprobante TEXT DEFAULT 'I',
            status TEXT DEFAULT 'vigente',
            metodo_pago TEXT,
            forma_pago TEXT,
            uso_cfdi TEXT,
            concepto TEXT,
            serie TEXT,
            folio TEXT,
            impuestos REAL DEFAULT 0,
            retenciones REAL DEFAULT 0,
            descuento REAL DEFAULT 0,
            xml_path TEXT,
            xml_status TEXT
        );
        CREATE TABLE IF NOT EXISTS sat_credentials (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            issuer_id INTEGER NOT NULL,
            validation_ok INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS sat_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            issuer_id INTEGER NOT NULL,
            status TEXT DEFAULT 'ok',
            created_at TEXT,
            finished_at TEXT,
            last_error TEXT
        );
        CREATE TABLE IF NOT EXISTS sat_sync_state (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            issuer_id INTEGER NOT NULL,
            last_run_at TEXT
        );
        CREATE TABLE IF NOT EXISTS customer_profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            issuer_id INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS issuer_products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            issuer_id INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY
        );
        CREATE TABLE IF NOT EXISTS foreign_invoices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            issuer_id INTEGER NOT NULL,
            tipo TEXT NOT NULL,
            fecha TEXT NOT NULL,
            invoice_number TEXT NOT NULL,
            empresa TEXT NOT NULL,
            pais TEXT,
            tax_id TEXT,
            descripcion TEXT NOT NULL DEFAULT '',
            moneda TEXT NOT NULL DEFAULT 'USD',
            monto_original REAL NOT NULL,
            tipo_cambio REAL NOT NULL,
            monto_mxn REAL NOT NULL,
            forma_pago TEXT,
            referencia_pago TEXT,
            archivo TEXT,
            period_month TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS issuer_fiscal_profile (
            issuer_id INTEGER PRIMARY KEY,
            regimen TEXT NOT NULL DEFAULT 'RESICO_PF',
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        INSERT INTO issuers (id, rfc, alias) VALUES (1, 'TEST010101AAA', 'Test Co');
        INSERT INTO users (id, email) VALUES (1, 'test@test.com');
        INSERT INTO memberships (user_id, issuer_id, role) VALUES (1, 1, 'owner');
        INSERT INTO sat_cfdi (issuer_id, uuid, direction, fecha_emision, total, subtotal, impuestos, retenciones)
            VALUES (1, 'aaa-111', 'issued', '2026-05-01', 11600, 10000, 1600, 0);
        INSERT INTO sat_cfdi (issuer_id, uuid, direction, fecha_emision, total, subtotal, impuestos, retenciones)
            VALUES (1, 'bbb-222', 'received', '2026-05-05', 5800, 5000, 800, 0);
    """)
    conn.commit()
    conn.close()

    original = database.DB_PATH
    database.DB_PATH = db_path
    yield db_path
    database.DB_PATH = original


def test_fiscal_route_renders(fiscal_db):
    """Verify /portal/fiscal returns 200 with expected content."""
    from starlette.testclient import TestClient
    from app import app

    cookies = make_session_cookie(issuer_id=1, user_id=1)
    client = TestClient(app, cookies=cookies, raise_server_exceptions=False)

    resp = client.get("/portal/fiscal?ym=2026-05")
    assert resp.status_code == 200, f"Got {resp.status_code}: {resp.text[:500]}"
    body = resp.text
    assert "Resumen Fiscal" in body
    assert "ISR" in body
    assert "IVA" in body
    assert "RESICO" in body or "Empresarial" in body
