"""
Rate limit por IP: ventana deslizante respaldada en SQLite.

Persiste entre reinicios y funciona con multi-worker (Gunicorn).
Usado en auth (login, register, forgot, reset) y en portal (FIEL upload, validate, sat_sync).
API: is_rate_limited(request, key_prefix) -> True si se debe bloquear (429/redirect).
"""
from __future__ import annotations

import logging
import sqlite3
import time

from fastapi import Request

from database import db

logger = logging.getLogger(__name__)

_DEFAULT_WINDOW = 60.0
_DEFAULT_MAX = 10
_table_ready = False


def _ensure_table(conn: sqlite3.Connection) -> None:
    global _table_ready
    if _table_ready:
        return
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS rate_limit_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key TEXT NOT NULL,
            ts REAL NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_rate_limit_key_ts ON rate_limit_attempts (key, ts)"
    )
    _table_ready = True


def get_client_ip(request: Request) -> str:
    """IP del cliente: X-Forwarded-For, X-Real-IP o request.client.host."""
    raw = request.headers.get("x-forwarded-for") or request.headers.get("x-real-ip")
    if not raw and getattr(request, "client", None):
        raw = getattr(request.client, "host", None)
    return (raw or "").split(",")[0].strip() or "unknown"


def is_rate_limited(
    request: Request,
    key_prefix: str,
    *,
    window_seconds: float = _DEFAULT_WINDOW,
    max_attempts: int = _DEFAULT_MAX,
) -> bool:
    """
    True si la petición debe bloquearse por rate limit (máx. intentos en ventana).
    Si no, registra el intento y devuelve False.
    Clave: key_prefix + ":" + IP.
    Usa BEGIN IMMEDIATE para evitar race conditions en burst attacks.
    """
    ip = get_client_ip(request)
    key = f"{key_prefix}:{ip}"
    now = time.time()
    cutoff = now - window_seconds

    conn = db()
    try:
        _ensure_table(conn)
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute("DELETE FROM rate_limit_attempts WHERE key = ? AND ts < ?", (key, cutoff))
            row = conn.execute(
                "SELECT COUNT(*) AS cnt FROM rate_limit_attempts WHERE key = ? AND ts >= ?",
                (key, cutoff),
            ).fetchone()
            count = row["cnt"] if row else 0
            if count >= max_attempts:
                conn.rollback()
                return True
            conn.execute(
                "INSERT INTO rate_limit_attempts (key, ts) VALUES (?, ?)",
                (key, now),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    finally:
        conn.close()
    return False


def cleanup_old_entries(max_age_seconds: float = 3600.0) -> int:
    """Limpia entradas más viejas que max_age_seconds. Llamar desde startup."""
    cutoff = time.time() - max_age_seconds
    conn = db()
    try:
        _ensure_table(conn)
        cur = conn.execute("DELETE FROM rate_limit_attempts WHERE ts < ?", (cutoff,))
        conn.commit()
        deleted = cur.rowcount
        if deleted > 0:
            logger.info("rate_limit cleanup: %d old entries removed", deleted)
        return deleted
    finally:
        conn.close()
