#!/usr/bin/env python3
"""
Comprueba si la contraseña indicada coincide con la de usuarios que puedan ser "Diego".
Uso (desde la raíz del proyecto):
  python scripts/check_diego_password.py
  python scripts/check_diego_password.py "diegoesgay?"
"""
import sys
import os

# Asegurar que el proyecto está en el path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import db_rows
from services.users import get_user_password_hash, verify_password


def main():
    password_to_check = (sys.argv[1] if len(sys.argv) > 1 else "diegoesgay?").strip()

    # Listar todos los usuarios (id, email, name)
    rows = db_rows(
        "SELECT id, email, name FROM users ORDER BY id"
    )
    if not rows:
        print("No hay usuarios en la base de datos.")
        return

    # Buscar usuarios que puedan ser Diego (email o nombre contenga "diego")
    candidates = [
        r for r in rows
        if "diego" in (r.get("email") or "").lower() or "diego" in (r.get("name") or "").lower()
    ]
    if not candidates:
        print("No se encontró ningún usuario con 'diego' en email o nombre.")
        print("Usuarios en la base de datos:")
        for r in rows:
            print(f"  id={r['id']} email={r.get('email')} name={r.get('name')}")
        return

    print(f"Contraseña a verificar: {'*' * len(password_to_check)} ({len(password_to_check)} chars)")
    print()

    for u in candidates:
        uid = u["id"]
        email = u.get("email") or "(sin email)"
        name = u.get("name") or "(sin nombre)"
        hashed = get_user_password_hash(uid)
        if not hashed:
            print(f"Usuario id={uid} ({email}, {name}): no tiene password_hash → no puede entrar con contraseña.")
            continue
        ok = verify_password(password_to_check, hashed)
        if ok:
            print(f"Usuario id={uid} ({email}, {name}): SÍ coincide la contraseña.")
        else:
            print(f"Usuario id={uid} ({email}, {name}): NO coincide la contraseña (el hash no corresponde a esa contraseña).")

    print()
    print("Si no coincide, la contraseña guardada es otra. Puedes restablecerla desde 'Olvidé mi contraseña' o actualizando el hash en la BD.")


if __name__ == "__main__":
    main()
