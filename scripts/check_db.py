#!/usr/bin/env python3
"""
Script opcional para verificar el estado de la base de datos (invoicing).
Imprime: tablas críticas, PRAGMA table_info(issuers), conteos en sat_cfdi e invoices.
Uso: APP_DB_PATH=invoicing_old.db python scripts/check_db.py
"""
import os
import sqlite3
from pathlib import Path

# Misma lógica que app.py para DB_PATH
BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = os.getenv("APP_DB_PATH") or str(BASE_DIR / "invoicing.db")

# Tablas que la app espera (según 001_baseline y uso en app.py)
CRITICAL_TABLES = [
    "schema_migrations",
    "issuers",
    "issuer_tokens",
    "sat_credentials",
    "sat_sync_state",
    "sat_cfdi",
    "sat_requests",
    "sat_jobs",
    "customer_profiles",
    "supplier_profiles",
    "issuer_products",
    "quotations",
    "quotation_items",
    "invoices",
    "invoice_items",
    "payment_relations",
]

REQUIRED_ISSUERS_COLUMN = "facturapi_org_id"


def main() -> None:
    print(f"DB: {DB_PATH}")
    if not os.path.isfile(DB_PATH):
        print("  (archivo no existe; se creará al arrancar la app)")
        return

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        # 1) Lista de tablas críticas
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        existing_tables = {row[0] for row in cur.fetchall()}

        print("\n--- Tablas críticas ---")
        for t in CRITICAL_TABLES:
            status = "ok" if t in existing_tables else "FALTA"
            print(f"  {t}: {status}")

        # 2) PRAGMA table_info(issuers) y comprobar facturapi_org_id
        print("\n--- PRAGMA table_info(issuers) ---")
        if "issuers" not in existing_tables:
            print("  (tabla issuers no existe)")
        else:
            cur = conn.execute("PRAGMA table_info(issuers)")
            rows = cur.fetchall()
            col_names = [r[1] for r in rows]
            for r in rows:
                print(f"  {r[1]} {r[2]}")
            if REQUIRED_ISSUERS_COLUMN in col_names:
                print(f"  -> {REQUIRED_ISSUERS_COLUMN}: existe")
            else:
                print(f"  -> {REQUIRED_ISSUERS_COLUMN}: FALTA (la migración 001 la añade)")

        # 3) Conteo sat_cfdi e invoices (si existen)
        print("\n--- Conteo de filas ---")
        for table in ("sat_cfdi", "invoices"):
            if table not in existing_tables:
                print(f"  {table}: (tabla no existe)")
                continue
            cur = conn.execute(f"SELECT COUNT(*) FROM {table}")
            n = cur.fetchone()[0]
            print(f"  {table}: {n} filas")

        # Usuarios que pueden entrar al portal (issuers + tokens)
        print("\n--- Usuarios (portal: usar token en /login?token=XXX) ---")
        if "issuers" in existing_tables and "issuer_tokens" in existing_tables:
            cur = conn.execute("""
                SELECT i.id, i.rfc, i.razon_social, t.token, t.active AS token_active
                FROM issuers i
                JOIN issuer_tokens t ON t.issuer_id = i.id
                WHERE i.active = 1
                ORDER BY i.id
            """)
            rows = cur.fetchall()
            if not rows:
                print("  (ninguno; ejecuta: python3 scripts/ensure_demo_user.py)")
            for r in rows:
                tok_ok = "activo" if r["token_active"] else "inactivo"
                print(f"  id={r['id']}  {r['razon_social'] or r['rfc'] or '—'}  token={r['token']} ({tok_ok})")
                print(f"    -> http://127.0.0.1:8000/portal/home?token={r['token']}")
        else:
            print("  (tablas issuers/issuer_tokens no existen)")

        # Bonus: versiones aplicadas
        if "schema_migrations" in existing_tables:
            cur = conn.execute("SELECT version, applied_at FROM schema_migrations ORDER BY version")
            rows = cur.fetchall()
            print("\n--- schema_migrations ---")
            for r in rows:
                print(f"  {r[0]} @ {r[1]}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
