# --- OBSOLETO ---
# Script deprecado. La fuente de verdad es migrations/ + migrations_runner.py.
# Ver MIGRATION_LEGACY_MAP.md en la raíz del proyecto. No ejecutar.
# ---

#!/usr/bin/env python3
"""
Añade usuario David Venegas (RFC VEND980918UR1, RESICO).
Token de acceso al portal: Deind9809
  → URL: /portal/home?token=Deind9809
"""
import os
import sqlite3

_PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.getenv("APP_DB_PATH") or os.path.join(_PROJECT_DIR, "invoicing.db")

RFC = "VEND980918UR1"
RAZON_SOCIAL = "David Venegas"
REGIMEN_FISCAL = "626"  # RESICO (código SAT)
TOKEN_PORTAL = "Deind9809"


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.row_factory = sqlite3.Row

    existing = conn.execute("SELECT id FROM issuers WHERE rfc = ?", (RFC,)).fetchone()
    if existing:
        print(f"  {RFC} ({RAZON_SOCIAL}) ya existe en issuers (id={existing['id']}).")
        # Actualizar régimen por si acaso
        conn.execute(
            "UPDATE issuers SET regimen_fiscal = ?, razon_social = ? WHERE rfc = ?",
            (REGIMEN_FISCAL, RAZON_SOCIAL, RFC),
        )
        conn.commit()
        issuer_id = existing["id"]
        # Asegurar que tiene token
        tok = conn.execute(
            "SELECT id FROM issuer_tokens WHERE issuer_id = ? AND token = ?",
            (issuer_id, TOKEN_PORTAL),
        ).fetchone()
        if not tok:
            conn.execute(
                "INSERT INTO issuer_tokens (issuer_id, token, active) VALUES (?, ?, 1)",
                (issuer_id, TOKEN_PORTAL),
            )
            conn.commit()
            print(f"  Token de portal añadido: {TOKEN_PORTAL}")
        conn.close()
        print(f"\n✅ Usuario listo. Acceso: /portal/home?token={TOKEN_PORTAL}")
        return

    conn.execute(
        """
        INSERT INTO issuers (rfc, razon_social, regimen_fiscal, active)
        VALUES (?, ?, ?, 1)
        """,
        (RFC, RAZON_SOCIAL, REGIMEN_FISCAL),
    )
    issuer_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    try:
        conn.execute(
            "INSERT INTO issuer_tokens (issuer_id, token, active) VALUES (?, ?, 1)",
            (issuer_id, TOKEN_PORTAL),
        )
        token_used = TOKEN_PORTAL
    except sqlite3.IntegrityError:
        alt = f"{TOKEN_PORTAL}_{RFC[:4]}"
        conn.execute(
            "INSERT INTO issuer_tokens (issuer_id, token, active) VALUES (?, ?, 1)",
            (issuer_id, alt),
        )
        token_used = alt
        print(f"  Token '{TOKEN_PORTAL}' ya existía, usando: {token_used}")

    conn.commit()
    conn.close()
    print(f"  + {RFC} ({RAZON_SOCIAL}) -> issuer_id={issuer_id}, token={token_used}")
    print(f"\n✅ Usuario creado. Acceso al portal: /portal/home?token={token_used}")


if __name__ == "__main__":
    main()
