"""
Lógica de productos (issuer_products / products) aislada de HTTP.
"""

from __future__ import annotations

from typing import Tuple

from database import db, table_exists
from services.db_utils import fetch_all, scalar, execute
from services.schemas import ProductCreate


def list_products(issuer_id: int, limit: int, offset: int) -> Tuple[list[dict], int]:
    """
    Lista productos de la tabla `products` (si existe) o `issuer_products` como fallback.
    """
    conn = db()
    try:
        if table_exists(conn, "products"):
            total = scalar(
                conn,
                "SELECT COUNT(*) FROM products WHERE issuer_id = ?",
                (issuer_id,),
            ) or 0
            rows = fetch_all(
                conn,
                """
                SELECT id, name, clave_prod_serv, clave_unidad, unidad, default_unit_price, default_currency, updated_at
                FROM products
                WHERE issuer_id = ? AND COALESCE(active, 1) = 1
                ORDER BY name
                LIMIT ? OFFSET ?
                """,
                (issuer_id, limit, offset),
            )
            items = [
                {
                    "id": r["id"],
                    "description": r.get("name") or "",
                    "product_key": r.get("clave_prod_serv") or "",
                    "unit_key": r.get("clave_unidad") or "E48",
                    "unit_price": float(r.get("default_unit_price") or 0),
                    "iva_rate": 0.16,
                    "created_at": r.get("updated_at"),
                }
                for r in rows
            ]
            return items, int(total)

        total = scalar(
            conn,
            "SELECT COUNT(*) FROM issuer_products WHERE issuer_id = ?",
            (issuer_id,),
        ) or 0
        rows = fetch_all(
            conn,
            """
            SELECT id, description, product_key, unit_key, unit_price, iva_rate, created_at
            FROM issuer_products
            WHERE issuer_id = ?
            ORDER BY description
            LIMIT ? OFFSET ?
            """,
            (issuer_id, limit, offset),
        )
        items = [
            {
                "id": r["id"],
                "description": r["description"],
                "product_key": r["product_key"],
                "unit_key": r["unit_key"],
                "unit_price": float(r.get("unit_price") or 0),
                "iva_rate": float(r.get("iva_rate") or 0.16),
                "created_at": r.get("created_at"),
            }
            for r in rows
        ]
        return items, int(total)
    finally:
        conn.close()


def create_product(issuer_id: int, payload: ProductCreate) -> int:
    """
    Crea un producto en issuer_products.
    Devuelve el ID insertado.
    """
    conn = db()
    try:
        execute(
            conn,
            """
            INSERT INTO issuer_products (issuer_id, description, product_key, unit_key, unit_price, iva_rate)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                issuer_id,
                payload.description,
                payload.product_key,
                payload.unit_key or "E48",
                float(payload.unit_price),
                float(payload.iva_rate),
            ),
        )
        conn.commit()
        row_id = scalar(conn, "SELECT last_insert_rowid()") or 0
        return int(row_id)
    finally:
        conn.close()

