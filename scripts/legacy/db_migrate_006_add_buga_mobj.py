# --- OBSOLETO ---
# Script deprecado. La fuente de verdad es migrations/ + migrations_runner.py.
# Ver MIGRATION_LEGACY_MAP.md en la raíz del proyecto. No ejecutar.
# ---

#!/usr/bin/env python3
"""
Migración 006: Registrar Carolina Bucio (BUGA) y Manuel Montoya (MOBJ)
en issuers, sat_credentials e issuer_tokens.
Rutas de keys/ según carpetas: keys/BUGA020405GU7 y keys/MOBJ970402176.

IMPORTANTE: Debes configurar la contraseña FIEL de cada cliente.
  sqlite3 invoicing.db "UPDATE sat_credentials SET fiel_key_password='TU_PASSWORD' WHERE issuer_id IN (2,3);"
"""
import os
import sqlite3

_PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.getenv("APP_DB_PATH") or os.path.join(_PROJECT_DIR, "invoicing.db")

# Configuración por RFC: (razon_social, token_portal, contraseña_placeholder)
CLIENTS = [
    {
        "rfc": "BUGA020405GU7",
        "razon_social": "Carolina Bucio",
        "token": "carolina",
        "cer": "keys/BUGA020405GU7/buga020405gu7.cer",
        "key": "keys/BUGA020405GU7/Claveprivada_FIEL_BUGA020405GU7_20250930_173637.key",
        "fiel_password": "CAMBIAR_BUGA",  # <-- Configurar contraseña real
    },
    {
        "rfc": "MOBJ970402176",
        "razon_social": "Manuel Montoya",
        "token": "manuel",
        "cer": "keys/MOBJ970402176/mobj970402176.cer",
        "key": "keys/MOBJ970402176/Claveprivada_FIEL_MOBJ970402176_20230301_094943.key",
        "fiel_password": "CAMBIAR_MOBJ",  # <-- Configurar contraseña real
    },
]


def main():
    base_dir = _PROJECT_DIR
    for c in CLIENTS:
        cer_full = os.path.join(base_dir, c["cer"].replace("/", os.sep))
        key_full = os.path.join(base_dir, c["key"].replace("/", os.sep))
        if not os.path.exists(cer_full):
            raise FileNotFoundError(f"No existe: {cer_full}")
        if not os.path.exists(key_full):
            raise FileNotFoundError(f"No existe: {key_full}")

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.row_factory = sqlite3.Row

    for c in CLIENTS:
        # Evitar duplicados
        existing = conn.execute(
            "SELECT id FROM issuers WHERE rfc = ?", (c["rfc"],)
        ).fetchone()
        if existing:
            print(f"  {c['rfc']} ({c['razon_social']}) ya existe, omitiendo.")
            continue

        conn.execute(
            """
            INSERT INTO issuers (rfc, razon_social, created_at, updated_at, active)
            VALUES (?, ?, datetime('now'), datetime('now'), 1)
            """,
            (c["rfc"], c["razon_social"]),
        )
        issuer_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

        conn.execute(
            """
            INSERT INTO sat_credentials (issuer_id, fiel_cer_path, fiel_key_path, fiel_key_password)
            VALUES (?, ?, ?, ?)
            """,
            (issuer_id, c["cer"], c["key"], c["fiel_password"]),
        )

        try:
            conn.execute(
                """
                INSERT INTO issuer_tokens (issuer_id, token, active)
                VALUES (?, ?, 1)
                """,
                (issuer_id, c["token"]),
            )
        except sqlite3.IntegrityError:
            # token ya existe, intentar con variante
            alt_token = f"{c['token']}_{c['rfc'][:4]}"
            conn.execute(
                """
                INSERT INTO issuer_tokens (issuer_id, token, active)
                VALUES (?, ?, 1)
                """,
                (issuer_id, alt_token),
            )
            c["token"] = alt_token
            print(f"  Token '{c['token']}' ya existía, usando: {alt_token}")

        print(f"  + {c['rfc']} ({c['razon_social']}) -> issuer_id={issuer_id}, token={c['token']}")

    conn.commit()
    conn.close()

    print(f"\n✅ Migración 006 OK en: {DB_PATH}")
    print("\n⚠️  Configura las contraseñas FIEL reales en sat_credentials")


if __name__ == "__main__":
    main()
