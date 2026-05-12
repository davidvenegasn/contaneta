#!/usr/bin/env python3
"""
Pone a Diego y Carolina en plan Pro (más servicios: descarga XML/PDF, etc.).
Identifica usuarios por email: diegopgza@gmail.com, carobucio7@gmail.com.
"""
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

try:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / ".env")
except ImportError:
    pass

# Emails de Diego y Carolina (mismo orden que link_issuers_to_users.py)
PRO_USERS_EMAILS = [
    "diegopgza@gmail.com",   # Diego Garza
    "carobucio7@gmail.com",  # Carolina Bucio
]


def main():
    from config import DB_PATH
    if not os.path.isfile(DB_PATH):
        print(f"DB no existe: {DB_PATH}")
        sys.exit(1)

    from database import db
    from services.billing.subscription import upsert_subscription

    conn = db()
    try:
        for email in PRO_USERS_EMAILS:
            email = email.strip().lower()
            row = conn.execute(
                "SELECT id, email, name FROM users WHERE email = ? LIMIT 1",
                (email,),
            ).fetchone()
            if not row:
                print(f"  Usuario no encontrado: {email}")
                continue
            user_id = row["id"]
            name = row["name"] or email
            upsert_subscription(user_id, plan="pro", status="active")
            print(f"  Plan Pro asignado: {name} ({email}, user_id={user_id})")
    finally:
        conn.close()

    print("\n✅ Diego y Carolina están en plan Pro.")


if __name__ == "__main__":
    main()
