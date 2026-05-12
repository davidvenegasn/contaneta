# --- OBSOLETO ---
# Script deprecado. La fuente de verdad es migrations/ + migrations_runner.py.
# Ver MIGRATION_LEGACY_MAP.md en la raíz del proyecto. No ejecutar.
# ---

"""
Migración 009: índices en sat_cfdi para listados y búsqueda por UUID.
- (issuer_id, direction, fecha_emision): listados por mes y orden por fecha.
- (issuer_id, uuid): búsqueda de detalle por UUID.
"""
import os
import sqlite3

DB_PATH = os.getenv("APP_DB_PATH", "invoicing.db")


def index_exists(conn, name: str) -> bool:
    cur = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='index' AND name=? LIMIT 1",
        (name,),
    )
    return cur.fetchone() is not None


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")

    indexes = [
        (
            "idx_sat_cfdi_issuer_direction_fecha",
            "sat_cfdi(issuer_id, direction, fecha_emision)",
        ),
        ("idx_sat_cfdi_issuer_uuid", "sat_cfdi(issuer_id, uuid)"),
    ]

    for idx_name, idx_def in indexes:
        if not index_exists(conn, idx_name):
            try:
                conn.execute(f"CREATE INDEX {idx_name} ON {idx_def};")
                print(f"  ✅ Índice creado: {idx_name}")
            except sqlite3.OperationalError as e:
                print(f"  ⚠️  Error creando índice {idx_name}: {e}")
        else:
            print(f"  ⏭️  Índice ya existe: {idx_name}")

    conn.commit()
    conn.close()
    print(f"✅ Migración 009 OK (índices sat_cfdi) en DB: {DB_PATH}")


if __name__ == "__main__":
    main()
