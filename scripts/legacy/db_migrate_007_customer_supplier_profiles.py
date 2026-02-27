# --- OBSOLETO ---
# Script deprecado. La fuente de verdad es migrations/ + migrations_runner.py.
# Ver MIGRATION_LEGACY_MAP.md en la raíz del proyecto. No ejecutar.
# ---

#!/usr/bin/env python3
"""
Migración 007: Asegura que existan customer_profiles y supplier_profiles
para que cada usuario (issuer) pueda guardar sus clientes y proveedores.

- customer_profiles: clientes que el emisor agrega (para facturar)
- supplier_profiles: proveedores que el emisor agrega (de quienes recibe facturas)

Ambas tablas están asociadas a issuer_id (cada usuario tiene sus propios datos).
Campos opcionales: zip, tax_system para flexibilidad.

Ejecutar una sola vez: python db_migrate_007_customer_supplier_profiles.py
"""
import os
import sqlite3

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.getenv("APP_DB_PATH") or os.path.join(BASE_DIR, "invoicing.db")


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    r = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
        (name,),
    ).fetchone()
    return bool(r)


def migrate():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")

    # 1) customer_profiles
    if not _table_exists(conn, "customer_profiles"):
        conn.execute(
            """
            CREATE TABLE customer_profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                issuer_id INTEGER NOT NULL,
                rfc TEXT NOT NULL,
                legal_name TEXT NOT NULL,
                zip TEXT,
                tax_system TEXT,
                email TEXT,
                alias TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now')),
                UNIQUE(issuer_id, rfc),
                FOREIGN KEY (issuer_id) REFERENCES issuers(id) ON DELETE CASCADE
            );
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_customer_profiles_issuer_id ON customer_profiles(issuer_id);"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_customer_profiles_alias ON customer_profiles(alias);"
        )
        print("[OK] Tabla customer_profiles creada.")
    else:
        print("[OK] Tabla customer_profiles ya existe.")

    # 2) supplier_profiles
    if not _table_exists(conn, "supplier_profiles"):
        conn.execute(
            """
            CREATE TABLE supplier_profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                issuer_id INTEGER NOT NULL,
                rfc TEXT NOT NULL,
                legal_name TEXT NOT NULL,
                zip TEXT,
                tax_system TEXT,
                email TEXT,
                alias TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now')),
                UNIQUE(issuer_id, rfc),
                FOREIGN KEY (issuer_id) REFERENCES issuers(id) ON DELETE CASCADE
            );
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_supplier_profiles_issuer_id ON supplier_profiles(issuer_id);"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_supplier_profiles_alias ON supplier_profiles(alias);"
        )
        print("[OK] Tabla supplier_profiles creada.")
    else:
        print("[OK] Tabla supplier_profiles ya existe.")

    conn.commit()
    conn.close()
    print(f"✅ Migración 007 completada en: {DB_PATH}")


if __name__ == "__main__":
    migrate()
