# --- OBSOLETO ---
# Script deprecado. La fuente de verdad es migrations/ + migrations_runner.py.
# Ver MIGRATION_LEGACY_MAP.md en la raíz del proyecto. No ejecutar.
# ---

#!/usr/bin/env python3
"""
Migración 008: Añadir régimen fiscal a issuers (contexto por usuario).
- Añade columna regimen_fiscal TEXT a issuers.
- Asigna: GAZD (Diego Garza) = RESICO, Carolina Bucio (BUGA) = RESICO, Manuel Montoya (MOBJ) = AE.
"""
import os
import sqlite3

_PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.getenv("APP_DB_PATH") or os.path.join(_PROJECT_DIR, "invoicing.db")


def _has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    if table != "issuers":
        return False
    cur = conn.execute("PRAGMA table_info(issuers)")
    for row in cur:
        if row[1] == column:
            return True
    return False


# RFC -> régimen fiscal (etiqueta: RESICO, AE)
UPDATES = [
    ("GAZD970429MKA", "RESICO"),   # Diego Garza
    ("BUGA020405GU7", "RESICO"),   # Carolina Bucio
    ("MOBJ970402176", "AE"),       # Manuel Montoya (persona física con actividad empresarial)
]


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.row_factory = sqlite3.Row

    if not _has_column(conn, "issuers", "regimen_fiscal"):
        conn.execute("ALTER TABLE issuers ADD COLUMN regimen_fiscal TEXT;")
        conn.commit()
        print("  + Columna issuers.regimen_fiscal añadida.")

    for rfc, regimen in UPDATES:
        cur = conn.execute("SELECT id, rfc FROM issuers WHERE rfc = ?", (rfc,))
        row = cur.fetchone()
        if row:
            conn.execute(
                "UPDATE issuers SET regimen_fiscal = ? WHERE id = ?",
                (regimen, row["id"]),
            )
            print(f"  + {rfc} -> regimen_fiscal = {regimen}")
        else:
            print(f"  - {rfc} no encontrado en issuers, omitiendo.")

    conn.commit()
    conn.close()
    print(f"\n✅ Migración 008 OK en: {DB_PATH}")


if __name__ == "__main__":
    main()
