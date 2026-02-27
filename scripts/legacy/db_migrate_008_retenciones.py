# --- OBSOLETO ---
# Script deprecado. La fuente de verdad es migrations/ + migrations_runner.py.
# Ver MIGRATION_LEGACY_MAP.md en la raíz del proyecto. No ejecutar.
# ---

#!/usr/bin/env python3
"""
Migración 008: Agrega columna retenciones (TotalImpuestosRetenidos) a sat_cfdi
para poder mostrar retenciones de IVA/ISR en emitidas y recibidas.

Ejecutar una sola vez: python3 db_migrate_008_retenciones.py
"""
import os
import sqlite3

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.getenv("APP_DB_PATH") or os.path.join(BASE_DIR, "invoicing.db")


def column_exists(conn, table, col):
    cur = conn.execute(f"PRAGMA table_info({table})")
    return any(r[1] == col for r in cur.fetchall())


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    if not column_exists(conn, "sat_cfdi", "retenciones"):
        conn.execute("ALTER TABLE sat_cfdi ADD COLUMN retenciones REAL;")
        print("[OK] Columna sat_cfdi.retenciones creada.")
    else:
        print("[OK] Columna sat_cfdi.retenciones ya existe.")
    conn.commit()
    conn.close()
    print(f"✅ Migración 008 completada en: {DB_PATH}")


if __name__ == "__main__":
    main()
