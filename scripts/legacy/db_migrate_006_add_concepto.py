# --- OBSOLETO ---
# Script deprecado. La fuente de verdad es migrations/ + migrations_runner.py.
# Ver MIGRATION_LEGACY_MAP.md en la raíz del proyecto. No ejecutar.
# ---

#!/usr/bin/env python3
"""Agrega columna concepto a sat_cfdi para guardar descripción del primer concepto."""
import os
import sqlite3

DB_PATH = os.getenv("APP_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "invoicing.db"
)


def column_exists(conn, table, col):
    cur = conn.execute(f"PRAGMA table_info({table})")
    return any(r[1] == col for r in cur.fetchall())


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    if not column_exists(conn, "sat_cfdi", "concepto"):
        conn.execute("ALTER TABLE sat_cfdi ADD COLUMN concepto TEXT;")
        conn.commit()
        print("✅ Columna concepto agregada a sat_cfdi")
    else:
        print("⏭️  Columna concepto ya existe")
    conn.close()


if __name__ == "__main__":
    main()
