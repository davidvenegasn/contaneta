"""Usuarios y memberships."""
from __future__ import annotations

import re
from typing import Any, Optional

import bcrypt

from config import FIRM_USER_EMAIL
from database import db, db_rows


def _user_from_row(row: Any) -> dict[str, Any] | None:
    if not row:
        return None
    if isinstance(row, dict):
        d = row
    elif hasattr(row, "keys"):
        d = dict(zip(row.keys(), row))
    else:
        try:
            d = dict(row)
        except Exception:
            return None
    return {"id": d.get("id"), "email": d.get("email"), "phone": d.get("phone"), "name": d.get("name")}


def validate_password_strength(plain: str) -> str | None:
    """Retorna mensaje de error si el password es débil, o None si es válido."""
    if len(plain) < 8:
        return "La contraseña debe tener mínimo 8 caracteres."
    return None


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def verify_password(plain: str, hashed: str) -> bool:
    if not hashed:
        return False
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("ascii"))
    except Exception:
        return False


def get_user_by_email(email: str) -> dict[str, Any] | None:
    if not (email and str(email).strip()):
        return None
    # Verificar si la columna active existe antes de usarla
    from database import db, has_column
    conn = db()
    try:
        has_active = has_column(conn, "users", "active")
        if has_active:
            sql = "SELECT id, email, phone, name FROM users WHERE email = ? AND (active IS NULL OR active = 1) LIMIT 1"
        else:
            sql = "SELECT id, email, phone, name FROM users WHERE email = ? LIMIT 1"
        rows = db_rows(sql, (email.strip().lower(),))
        return _user_from_row(rows[0]) if rows else None
    finally:
        conn.close()


def get_user_by_phone(phone: str) -> dict[str, Any] | None:
    if not (phone and str(phone).strip()):
        return None
    normalized = re.sub(r"\D", "", str(phone).strip())
    if not normalized:
        return None
    # Verificar si la columna active existe antes de usarla
    from database import db, has_column
    conn = db()
    try:
        has_active = has_column(conn, "users", "active")
        if has_active:
            sql = "SELECT id, email, phone, name FROM users WHERE (REPLACE(REPLACE(phone, ' ', ''), '-', '') = ? OR phone = ?) AND (active IS NULL OR active = 1) LIMIT 1"
        else:
            sql = "SELECT id, email, phone, name FROM users WHERE (REPLACE(REPLACE(phone, ' ', ''), '-', '') = ? OR phone = ?) LIMIT 1"
        rows = db_rows(sql, (normalized, str(phone).strip()))
        return _user_from_row(rows[0]) if rows else None
    finally:
        conn.close()


def get_user_by_email_or_phone(login: str) -> dict[str, Any] | None:
    if not (login and str(login).strip()):
        return None
    s = str(login).strip()
    if "@" in s:
        return get_user_by_email(s)
    return get_user_by_phone(s)


def get_user_by_id(user_id: int) -> dict[str, Any] | None:
    if not user_id:
        return None
    rows = db_rows("SELECT id, email, phone, name FROM users WHERE id = ? LIMIT 1", (user_id,))
    return _user_from_row(rows[0]) if rows else None


def get_user_password_hash(user_id: int) -> Optional[str]:
    rows = db_rows("SELECT password_hash FROM users WHERE id = ? LIMIT 1", (user_id,))
    return rows[0]["password_hash"] if rows else None


def create_user(
    *,
    email: Optional[str] = None,
    phone: Optional[str] = None,
    name: Optional[str] = None,
    password_hash: Optional[str] = None,
    oauth_provider: Optional[str] = None,
    oauth_id: Optional[str] = None,
) -> dict[str, Any] | None:
    email = (email or "").strip().lower() or None
    phone = (phone or "").strip() or None
    name = (name or "").strip() or None
    if not email and not phone and not (oauth_provider and oauth_id):
        raise ValueError("Se requiere email, teléfono o OAuth.")
    conn = db()
    try:
        cur = conn.execute(
            """INSERT INTO users (email, phone, name, password_hash, oauth_provider, oauth_id)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (email, phone, name, password_hash or None, oauth_provider or None, oauth_id or None),
        )
        conn.commit()
        uid = cur.lastrowid
    finally:
        conn.close()
    return get_user_by_id(uid)


def update_user_name(user_id: int, name: Optional[str]) -> None:
    name = (name or "").strip() or None
    conn = db()
    try:
        conn.execute("UPDATE users SET name = ? WHERE id = ?", (name, user_id))
        conn.commit()
    finally:
        conn.close()


def update_user_password(user_id: int, password_hash: str) -> None:
    if not user_id or not password_hash:
        return
    conn = db()
    try:
        from database import has_column
        if has_column(conn, "users", "password_changed_at"):
            conn.execute(
                "UPDATE users SET password_hash = ?, password_changed_at = datetime('now') WHERE id = ?",
                (password_hash, user_id),
            )
        else:
            conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (password_hash, user_id))
        conn.commit()
    finally:
        conn.close()


def get_or_create_user_by_oauth(
    provider: str,
    oauth_id: str,
    email: Optional[str] = None,
    phone: Optional[str] = None,
    name: Optional[str] = None,
) -> dict[str, Any] | None:
    rows = db_rows(
        "SELECT id, email, phone, name FROM users WHERE oauth_provider = ? AND oauth_id = ? LIMIT 1",
        (provider, oauth_id),
    )
    if rows:
        return _user_from_row(rows[0])
    return create_user(
        email=email or None,
        phone=phone or None,
        name=name or None,
        oauth_provider=provider,
        oauth_id=oauth_id,
    )


def get_memberships_for_user(user_id: int) -> list[dict]:
    return db_rows(
        """SELECT m.id, m.user_id, m.issuer_id, m.role, i.rfc, i.razon_social
           FROM memberships m JOIN issuers i ON i.id = m.issuer_id
           WHERE m.user_id = ? AND i.active = 1 ORDER BY i.razon_social""",
        (user_id,),
    )


def get_membership(user_id: int, issuer_id: int) -> Optional[dict]:
    rows = db_rows(
        "SELECT user_id, issuer_id, role FROM memberships WHERE user_id = ? AND issuer_id = ? LIMIT 1",
        (user_id, issuer_id),
    )
    return rows[0] if rows else None


def user_has_admin_role(user_id: int) -> bool:
    """True si el usuario tiene al menos una membership con role 'admin'."""
    if not user_id or user_id <= 0:
        return False
    rows = db_rows(
        "SELECT 1 FROM memberships WHERE user_id = ? AND role = 'admin' LIMIT 1",
        (user_id,),
    )
    return len(rows) > 0


def user_has_admin_or_owner_role(user_id: int) -> bool:
    """True si el usuario tiene al menos una membership con role 'admin' o 'owner' (acceso al panel admin)."""
    if not user_id or user_id <= 0:
        return False
    rows = db_rows(
        "SELECT 1 FROM memberships WHERE user_id = ? AND role IN ('admin', 'owner') LIMIT 1",
        (user_id,),
    )
    return len(rows) > 0


def add_membership(user_id: int, issuer_id: int, role: str) -> None:
    conn = db()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO memberships (user_id, issuer_id, role) VALUES (?, ?, ?)",
            (user_id, issuer_id, role),
        )
        conn.commit()
    finally:
        conn.close()


def get_firm_user_id() -> Optional[int]:
    if not FIRM_USER_EMAIL:
        return None
    u = get_user_by_email(FIRM_USER_EMAIL)
    return u["id"] if u else None
