#!/usr/bin/env python3
"""
Vincula emisores existentes (por RFC) con usuarios de correo + contraseña.
Crea el usuario en `users` si no existe y añade `memberships` (rol owner) al issuer.

Uso (con el mismo entorno donde corre la app, para tener passlib):
    python scripts/link_issuers_to_users.py
    # o:  .venv/bin/python scripts/link_issuers_to_users.py

Los pares email/contraseña/RFC se definen en LINK_ISSUERS_CONFIG más abajo.
"""
import os
import sqlite3
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

# Usar bcrypt directamente (compatible con lo que la app guarda y verifica con passlib)
try:
    import bcrypt
    def hash_password(plain: str) -> str:
        return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("ascii")
except ImportError:
    print("Instala bcrypt: pip install bcrypt")
    sys.exit(1)

DB_PATH = os.getenv("APP_DB_PATH") or str(BASE_DIR / "invoicing.db")

# (email, contraseña_plana, RFC del issuer en la DB)
LINK_ISSUERS_CONFIG = [
    ("carobucio7@gmail.com", "caroesgay", "BUGA020405GU7"),   # Carolina Bucio
    ("diegopgza@gmail.com", "diegoesgay", "GAZD970429MKA"),   # Diego Garza
]


def main():
    if load_dotenv:
        load_dotenv(BASE_DIR / ".env")
    if not os.path.isfile(DB_PATH):
        print(f"DB no existe: {DB_PATH}")
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.row_factory = sqlite3.Row

    for email, password, rfc in LINK_ISSUERS_CONFIG:
        email = email.strip().lower()
        if not email or not password:
            print(f"  Omitiendo entrada vacía para RFC {rfc}")
            continue

        row = conn.execute(
            "SELECT id, razon_social FROM issuers WHERE rfc = ? AND active = 1 LIMIT 1",
            (rfc,),
        ).fetchone()
        if not row:
            print(f"  Issuer con RFC {rfc} no encontrado o inactivo. Omitiendo.")
            continue

        issuer_id = row["id"]
        razon = row["razon_social"]

        user_row = conn.execute(
            "SELECT id FROM users WHERE email = ? LIMIT 1",
            (email,),
        ).fetchone()

        if user_row:
            user_id = user_row["id"]
            print(f"  Usuario ya existe: {email} (user_id={user_id})")
        else:
            password_hash = hash_password(password)
            conn.execute(
                """
                INSERT INTO users (email, password_hash)
                VALUES (?, ?)
                """,
                (email, password_hash),
            )
            user_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            print(f"  Usuario creado: {email} (user_id={user_id})")

        existing_mem = conn.execute(
            "SELECT id FROM memberships WHERE user_id = ? AND issuer_id = ? LIMIT 1",
            (user_id, issuer_id),
        ).fetchone()
        if existing_mem:
            print(f"  Membership ya existe: {email} -> {razon} (RFC {rfc})")
        else:
            conn.execute(
                "INSERT OR IGNORE INTO memberships (user_id, issuer_id, role) VALUES (?, ?, 'owner')",
                (user_id, issuer_id),
            )
            print(f"  Membership creado: {email} -> {razon} (RFC {rfc})")

    conn.commit()
    conn.close()

    base = os.getenv("APP_BASE_URL", "http://127.0.0.1:8000")
    print("\n✅ Listo. Pueden entrar con correo y contraseña en:")
    print(f"   {base}/login")
    print("   Carolina: carobucio7@gmail.com  |  Diego: diegopgza@gmail.com")


if __name__ == "__main__":
    main()
