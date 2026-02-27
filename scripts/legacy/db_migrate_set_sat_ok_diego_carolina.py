# --- OBSOLETO ---
# Script deprecado. La fuente de verdad es migrations/ + migrations_runner.py.
# Ver MIGRATION_LEGACY_MAP.md en la raíz del proyecto. No ejecutar.
# ---

#!/usr/bin/env python3
"""
Marca SAT (FIEL) como configurado para Diego Garza y Carolina Bucio.
Pone validation_ok = 1 en sat_credentials para los issuers con RFC GAZD970429MKA y BUGA020405GU7.
Ejecutar una vez después de tener sus claves en la DB (p. ej. ya subidas por la app o por migración 006).

Uso:
  python db_migrate_set_sat_ok_diego_carolina.py
  # o:  APP_DB_PATH=/ruta/invoicing.db python db_migrate_set_sat_ok_diego_carolina.py
"""
import os
import sqlite3

_PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.getenv("APP_DB_PATH") or os.path.join(_PROJECT_DIR, "invoicing.db")

# Diego Garza, Carolina Bucio (Caro)
RFCs = ("GAZD970429MKA", "BUGA020405GU7")


def _has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    cur = conn.execute(f"PRAGMA table_info({table})")
    return any(row[1] == column for row in cur.fetchall())


def main():
    if not os.path.isfile(DB_PATH):
        print(f"DB no encontrada: {DB_PATH}")
        return 1

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # Asegurar columnas validation_* en sat_credentials
    for col, col_type in [
        ("validation_at", "TEXT"),
        ("validation_ok", "INTEGER"),
        ("validation_message", "TEXT"),
    ]:
        if not _has_column(conn, "sat_credentials", col):
            conn.execute(f"ALTER TABLE sat_credentials ADD COLUMN {col} {col_type};")
            print(f"  + Columna sat_credentials.{col} añadida.")

    placeholders = ",".join("?" * len(RFCs))
    issuers = conn.execute(
        f"SELECT id, rfc, razon_social FROM issuers WHERE rfc IN ({placeholders}) AND active = 1",
        RFCs,
    ).fetchall()

    updated = 0
    for row in issuers:
        issuer_id = row["id"]
        rfc = row["rfc"]
        name = row["razon_social"] or rfc
        cur = conn.execute(
            "SELECT 1 FROM sat_credentials WHERE issuer_id = ? LIMIT 1",
            (issuer_id,),
        ).fetchone()
        if not cur:
            print(f"  ⚠ {rfc} ({name}): no hay fila en sat_credentials, omitiendo.")
            continue
        conn.execute(
            """
            UPDATE sat_credentials
            SET validation_ok = 1, validation_at = datetime('now'), validation_message = 'OK'
            WHERE issuer_id = ?
            """,
            (issuer_id,),
        )
        updated += 1
        print(f"  ✓ {rfc} ({name}) -> SAT marcado como configurado (validation_ok = 1).")

    conn.commit()
    conn.close()

    print(f"\n✅ Listo. Actualizados {updated} emisor(es) en {DB_PATH}")
    return 0


if __name__ == "__main__":
    exit(main())
