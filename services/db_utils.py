"""
Helpers de acceso a DB (sqlite) sobre `database.db()`.

Objetivo:
- Reducir repetición de `conn.execute(...).fetchall()` en routers/services.
- Centralizar pequeños patrones comunes.
"""

from __future__ import annotations

from typing import Any, Iterable, Sequence

import sqlite3


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


def scalar(conn: sqlite3.Connection, sql: str, params: Sequence[Any] = ()) -> Any:
    cur = conn.execute(sql, params)
    row = cur.fetchone()
    if row is None:
        return None
    # sqlite3.Row soporta índices
    return row[0]

