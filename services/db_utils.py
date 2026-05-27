"""
Helpers de acceso a DB (sqlite) sobre `database.db()`.

Objetivo:
- Reducir repetición de `conn.execute(...).fetchall()` en routers/services.
- Centralizar pequeños patrones comunes.
"""

from __future__ import annotations

import sqlite3
from typing import Any, Iterable, Sequence


def fetch_one(conn: sqlite3.Connection, sql: str, params: Sequence[Any] = ()) -> dict | None:
    cur = conn.execute(sql, params)
    row = cur.fetchone()
    if row is None:
        return None
    return dict(row)


def fetch_all(conn: sqlite3.Connection, sql: str, params: Sequence[Any] = ()) -> list[dict]:
    cur = conn.execute(sql, params)
    rows = cur.fetchall()
    return [dict(r) for r in rows]


def execute(conn: sqlite3.Connection, sql: str, params: Sequence[Any] = ()) -> sqlite3.Cursor:
    return conn.execute(sql, params)


def execute_many(conn: sqlite3.Connection, sql: str, seq_params: Iterable[Sequence[Any]]) -> None:
    conn.executemany(sql, seq_params)


def escape_like(value: str) -> str:
    """Escape LIKE metacharacters (%, _, \\\\) for safe use in SQL LIKE clauses.

    The returned value should be used with ``ESCAPE '\\\\'`` in the SQL query.

    Args:
        value: Raw user input string.

    Returns:
        Escaped string safe for LIKE patterns.
    """
    return (
        value
        .replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )


def scalar(conn: sqlite3.Connection, sql: str, params: Sequence[Any] = ()) -> Any:
    cur = conn.execute(sql, params)
    row = cur.fetchone()
    if row is None:
        return None
    # `database.db()` usa row_factory dict; otros callers pueden usar sqlite3.Row/tuple.
    if isinstance(row, dict):
        try:
            return next(iter(row.values()))
        except StopIteration:
            return None
    return row[0]

