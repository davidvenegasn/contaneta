#!/usr/bin/env python3
"""
Migración: permite NULL en zip y tax_system de customer_profiles.
Ejecutar una sola vez: python db_migrate_customer_profiles_nullable.py
"""
import os
import sqlite3

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.getenv("APP_DB_PATH") or os.path.join(BASE_DIR, "invoicing.db")


def migrate():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = OFF;")  # temporal para migrar
    try:
        r = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='customer_profiles'"
        ).fetchone()
        if not r:
            print("[SKIP] customer_profiles no existe. Crear con app.py.")
            return

        # SQLite no permite ALTER COLUMN. Recreamos la tabla.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS customer_profiles_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                issuer_id INTEGER NOT NULL,
                rfc TEXT NOT NULL,
                legal_name TEXT NOT NULL,
                zip TEXT,
                tax_system TEXT,
                email TEXT,
                alias TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(issuer_id, rfc),
                FOREIGN KEY (issuer_id) REFERENCES issuers(id) ON DELETE CASCADE
            );
        """)
        conn.execute("""
            INSERT INTO customer_profiles_new
            SELECT id, issuer_id, rfc, legal_name, zip, tax_system, email, alias, created_at, updated_at
            FROM customer_profiles;
        """)
        conn.execute("DROP TABLE customer_profiles;")
        conn.execute("ALTER TABLE customer_profiles_new RENAME TO customer_profiles;")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_customer_profiles_issuer_id ON customer_profiles(issuer_id);"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_customer_profiles_alias ON customer_profiles(alias);"
        )
        conn.commit()
        print("[OK] customer_profiles: zip y tax_system ahora aceptan NULL.")
    except sqlite3.OperationalError as e:
        print(f"[ERROR] {e}")
        raise
    finally:
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.close()


if __name__ == "__main__":
    migrate()
