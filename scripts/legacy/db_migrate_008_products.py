# --- OBSOLETO ---
# Script deprecado. La fuente de verdad es migrations/ + migrations_runner.py.
# Ver MIGRATION_LEGACY_MAP.md en la raíz del proyecto. No ejecutar.
# ---

"""
Crea la tabla issuer_products para guardar productos/servicios del emisor
(descripción, ClaveProdServ, unidad SAT, precio unitario, IVA) y reutilizarlos al generar facturas.
"""
import os
import sqlite3

from dotenv import load_dotenv

load_dotenv()
DB_PATH = os.getenv("APP_DB_PATH", "invoicing.db")


def table_exists(conn, table):
    cur = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
        (table,),
    )
    return cur.fetchone() is not None


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")

    if not table_exists(conn, "issuer_products"):
        conn.execute("""
        CREATE TABLE issuer_products (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          issuer_id INTEGER NOT NULL,
          description TEXT NOT NULL,
          product_key TEXT NOT NULL,
          unit_key TEXT NOT NULL DEFAULT 'E48',
          unit_price REAL NOT NULL,
          iva_rate REAL NOT NULL DEFAULT 0.16,
          created_at TEXT NOT NULL DEFAULT (datetime('now')),
          FOREIGN KEY (issuer_id) REFERENCES issuers(id) ON DELETE CASCADE
        );
        """)
        conn.execute("CREATE INDEX idx_issuer_products_issuer ON issuer_products(issuer_id);")
        conn.commit()
        print("✅ Tabla issuer_products creada.")
    else:
        print("✅ Tabla issuer_products ya existe.")

    conn.close()


if __name__ == "__main__":
    main()
