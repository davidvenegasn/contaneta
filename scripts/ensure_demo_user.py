#!/usr/bin/env python3
"""
Crea un usuario demo en la base de datos si no existe ninguno con token "demo".
Sirve para desarrollo local: así puedes entrar al portal sin tener que crear
usuarios a mano.

Uso:
    python scripts/ensure_demo_user.py

Imprime el enlace directo para entrar al portal con ese usuario.
"""
import os
import sqlite3

load_dotenv = None
try:
    from dotenv import load_dotenv
except ImportError:
    pass

_PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEMO_RFC = "XAXX010101000"
DEMO_RAZON = "Usuario Demo (desarrollo)"
REGIMEN = "616"  # Sin obligaciones fiscales


def main():
    if load_dotenv:
        load_dotenv(os.path.join(_PROJECT_DIR, ".env"))
    db_path = os.getenv("APP_DB_PATH") or os.path.join(_PROJECT_DIR, "invoicing.db")
    demo_token = os.getenv("DEV_TOKEN", "demo")
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.row_factory = sqlite3.Row

    # ¿Ya existe un token "demo" (o el que ponga DEV_TOKEN)?
    row = conn.execute(
        "SELECT t.id, t.token, i.id AS issuer_id, i.razon_social FROM issuer_tokens t JOIN issuers i ON i.id = t.issuer_id WHERE t.token = ? AND t.active = 1 LIMIT 1",
        (demo_token,),
    ).fetchone()

    if row:
        conn.close()
        base = os.getenv("APP_BASE_URL", "http://127.0.0.1:8000")
        print(f"✅ Usuario demo ya existe: {row['razon_social']} (issuer_id={row['issuer_id']})")
        print(f"\n🔗 Enlace para entrar al portal (este usuario):")
        print(f"   {base}/portal/home?token={row['token']}")
        print(f"\n   O con sesión: ve a {base}/login?token={row['token']} y luego navega sin token en la URL.")
        return

    # Crear issuer demo
    conn.execute(
        """
        INSERT INTO issuers (rfc, razon_social, regimen_fiscal, active)
        VALUES (?, ?, ?, 1)
        """,
        (DEMO_RFC, DEMO_RAZON, REGIMEN),
    )
    issuer_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.execute(
        "INSERT INTO issuer_tokens (issuer_id, token, active) VALUES (?, ?, 1)",
        (issuer_id, demo_token),
    )
    conn.commit()
    conn.close()

    base = os.getenv("APP_BASE_URL", "http://127.0.0.1:8000")
    print(f"✅ Usuario demo creado: {DEMO_RAZON} (issuer_id={issuer_id}, token={demo_token})")
    print(f"\n🔗 Enlace para entrar al portal (este usuario):")
    print(f"   {base}/portal/home?token={demo_token}")
    print(f"\n   O con sesión: ve a {base}/login?token={demo_token} y luego navega sin token en la URL.")


if __name__ == "__main__":
    main()
