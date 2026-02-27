#!/usr/bin/env python3
"""Compara la cuenta de Diego con la de Caro para ver qué difiere."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import db_rows

# Todos los usuarios
users = db_rows("SELECT id, email, phone, name, password_hash FROM users ORDER BY id")
print("=== Usuarios en la BD ===")
for u in users:
    has_hash = "sí" if (u.get("password_hash") and u["password_hash"].strip()) else "NO"
    print(f"  id={u['id']} email={u.get('email')} name={u.get('name')} password_hash={has_hash}")

# Memberships por usuario
print("\n=== Memberships (user_id -> issuer_id, role) ===")
members = db_rows("SELECT user_id, issuer_id, role FROM memberships ORDER BY user_id, issuer_id")
for m in members:
    print(f"  user_id={m['user_id']} issuer_id={m['issuer_id']} role={m.get('role')}")

# Diego (por email o nombre)
diego = [u for u in users if u.get("email") and "diego" in (u.get("email") or "").lower()]
caro = [u for u in users if u.get("email") and "caro" in (u.get("email") or "").lower() or (u.get("name") or "").lower().startswith("caro")]
print("\n=== Usuario Diego ===")
if diego:
    d = diego[0]
    print(f"  id={d['id']} email={d['email']} name={d.get('name')}")
    d_mem = [m for m in members if m["user_id"] == d["id"]]
    print(f"  Memberships: {len(d_mem)} -> {d_mem}")
else:
    print("  No encontrado")
print("\n=== Usuario Caro ===")
if caro:
    c = caro[0]
    print(f"  id={c['id']} email={c['email']} name={c.get('name')}")
    c_mem = [m for m in members if m["user_id"] == c["id"]]
    print(f"  Memberships: {len(c_mem)} -> {c_mem}")
else:
    print("  No encontrado")

# Issuers activos
issuers = db_rows("SELECT id, rfc, razon_social, active FROM issuers ORDER BY id")
print("\n=== Issuers ===")
for i in issuers:
    print(f"  id={i['id']} active={i.get('active')} rfc={i.get('rfc')} razon={i.get('razon_social')}")
