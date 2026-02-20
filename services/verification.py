"""Verificación de email y recuperación de contraseña. Tokens en DB como hash."""
import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Optional

from config import SESSION_SECRET
from database import db, db_rows


def _token_hash(token: str) -> str:
    return hashlib.sha256((SESSION_SECRET + token).encode()).hexdigest()


def create_email_verification(user_id: int, expires_hours: int = 24) -> str:
    """Crea registro en email_verifications y devuelve el token en claro (para enviar por email)."""
    token = secrets.token_urlsafe(32)
    token_h = _token_hash(token)
    expires = (datetime.utcnow() + timedelta(hours=expires_hours)).strftime("%Y-%m-%d %H:%M:%S")
    conn = db()
    try:
        conn.execute(
            "INSERT INTO email_verifications (user_id, token_hash, expires_at) VALUES (?, ?, ?)",
            (user_id, token_h, expires),
        )
        conn.commit()
    finally:
        conn.close()
    return token


def verify_email_token(token: str) -> Optional[int]:
    """Si el token es válido y no expirado/usado, marca usado y devuelve user_id. Si no, None."""
    if not token or not token.strip():
        return None
    token_h = _token_hash(token.strip())
    conn = db()
    try:
        row = conn.execute(
            """SELECT id, user_id, expires_at FROM email_verifications
               WHERE token_hash = ? AND used_at IS NULL AND datetime(expires_at) > datetime('now')
               LIMIT 1""",
            (token_h,),
        ).fetchone()
        if not row:
            return None
        now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute("UPDATE email_verifications SET used_at = ? WHERE id = ?", (now, row["id"]))
        conn.commit()
        return row["user_id"]
    finally:
        conn.close()


def create_password_reset(user_id: int, expires_hours: int = 2) -> str:
    """Crea registro en password_resets y devuelve el token en claro."""
    token = secrets.token_urlsafe(32)
    token_h = _token_hash(token)
    expires = (datetime.utcnow() + timedelta(hours=expires_hours)).strftime("%Y-%m-%d %H:%M:%S")
    conn = db()
    try:
        conn.execute(
            "INSERT INTO password_resets (user_id, token_hash, expires_at) VALUES (?, ?, ?)",
            (user_id, token_h, expires),
        )
        conn.commit()
    finally:
        conn.close()
    return token


def consume_password_reset_token(token: str) -> Optional[int]:
    """Si el token es válido, marca usado y devuelve user_id. Si no, None."""
    if not token or not token.strip():
        return None
    token_h = _token_hash(token.strip())
    conn = db()
    try:
        row = conn.execute(
            """SELECT id, user_id FROM password_resets
               WHERE token_hash = ? AND used_at IS NULL AND datetime(expires_at) > datetime('now')
               LIMIT 1""",
            (token_h,),
        ).fetchone()
        if not row:
            return None
        now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute("UPDATE password_resets SET used_at = ? WHERE id = ?", (now, row["id"]))
        conn.commit()
        return row["user_id"]
    finally:
        conn.close()
