#!/usr/bin/env python3
# =============================================================================
# LEGACY — NO USAR EN PRODUCCIÓN NI COMO FUENTE DE SCHEMA
# =============================================================================
# Este script es un remanente del antiguo db_init.py. La app NO lo ejecuta.
# El schema se define ÚNICAMENTE por migraciones (migrations/*.sql).
# Solo usar para pruebas manuales con un schema muy antiguo; en todos los demás
# casos usar: arrancar la app (aplica migraciones) o crear DB vacía y arrancar.
# =============================================================================
"""
Script opcional de seed para desarrollo local (LEGACY).
Crea un schema básico compatible con versiones antiguas (antes de migraciones).

NOTA: Este script NO se ejecuta automáticamente.
La app usa migraciones (migrations/001_baseline.sql) como fuente única de verdad.
Ver MIGRATIONS.md para el flujo correcto.

Uso (solo si realmente necesitas un schema antiguo):
    python scripts/seed_dev.py
"""
import os
import sqlite3

from dotenv import load_dotenv

load_dotenv()
DB_PATH = os.getenv("APP_DB_PATH", "invoicing.db")

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS issuers (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  alias TEXT NOT NULL,
  rfc TEXT NOT NULL,
  facturapi_org_id TEXT NOT NULL,
  whatsapp_e164 TEXT, -- opcional (futuro)
  active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS issuer_tokens (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  issuer_id INTEGER NOT NULL,
  token TEXT NOT NULL UNIQUE,
  active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY (issuer_id) REFERENCES issuers(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS frequent_customers (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  issuer_id INTEGER NOT NULL,
  rfc TEXT NOT NULL,
  legal_name TEXT NOT NULL,
  zip TEXT NOT NULL,
  tax_system TEXT NOT NULL,    -- régimen fiscal receptor (cat SAT)
  cfdi_use TEXT NOT NULL,      -- uso CFDI
  email TEXT,
  facturapi_customer_id TEXT,  -- si decides registrarlo en Facturapi
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(issuer_id, rfc),
  FOREIGN KEY (issuer_id) REFERENCES issuers(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS invoices (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  issuer_id INTEGER NOT NULL,
  status TEXT NOT NULL DEFAULT 'created',
  currency TEXT NOT NULL DEFAULT 'MXN',
  exchange_rate REAL,
  payment_form TEXT NOT NULL,     -- forma de pago (cat SAT)
  payment_method TEXT NOT NULL,   -- PUE/PPD
  cfdi_use TEXT NOT NULL,
  customer_rfc TEXT NOT NULL,
  customer_legal_name TEXT NOT NULL,
  customer_zip TEXT NOT NULL,
  customer_tax_system TEXT NOT NULL,
  customer_email TEXT,
  facturapi_invoice_id TEXT,
  uuid TEXT,
  total REAL,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY (issuer_id) REFERENCES issuers(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS invoice_items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  invoice_id INTEGER NOT NULL,
  quantity REAL NOT NULL,
  description TEXT NOT NULL,
  product_key TEXT NOT NULL,   -- ClaveProdServ
  unit_price REAL NOT NULL,
  iva_rate REAL NOT NULL DEFAULT 0.16,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY (invoice_id) REFERENCES invoices(id) ON DELETE CASCADE
);
"""

def main():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()
    print(f"✅ DB seed lista en: {DB_PATH}")
    print("⚠️  NOTA: Este schema es solo para desarrollo/testing.")
    print("   La app usa migraciones (migrations/001_baseline.sql) como fuente única de verdad.")

if __name__ == "__main__":
    main()
