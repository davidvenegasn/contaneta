"""
Lógica de clientes (customer_profiles) aislada de HTTP.
"""

from __future__ import annotations

from typing import Tuple

from database import db
from services.db_utils import fetch_all, scalar, execute
from services.schemas import ClientCreate


def list_clients(issuer_id: int, limit: int, offset: int) -> Tuple[list[dict], int]:
    conn = db()
    try:
        total = scalar(
            conn,
            "SELECT COUNT(*) FROM customer_profiles WHERE issuer_id = ?",
            (issuer_id,),
        ) or 0
        rows = fetch_all(
            conn,
            """
            SELECT id, rfc, legal_name, zip, tax_system, email, alias
            FROM customer_profiles
            WHERE issuer_id = ?
            ORDER BY COALESCE(alias, ''), rfc
            LIMIT ? OFFSET ?
            """,
            (issuer_id, limit, offset),
        )
        return rows, int(total)
    finally:
        conn.close()


def upsert_client(issuer_id: int, payload: ClientCreate) -> str:
    """
    Crea o actualiza un cliente por (issuer_id, rfc).
    Devuelve el RFC normalizado.
    """
    conn = db()
    try:
        execute(
            conn,
            """
            INSERT INTO customer_profiles (issuer_id, rfc, legal_name, zip, tax_system, email, alias, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(issuer_id, rfc) DO UPDATE SET
                legal_name = excluded.legal_name,
                zip = excluded.zip,
                tax_system = excluded.tax_system,
                email = excluded.email,
                alias = excluded.alias,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                issuer_id,
                payload.rfc,
                payload.legal_name,
                payload.zip or "",
                payload.tax_system or "",
                payload.email or None,
                payload.alias or None,
            ),
        )
        conn.commit()
        return payload.rfc
    finally:
        conn.close()

