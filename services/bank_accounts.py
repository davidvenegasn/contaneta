"""
Cuentas bancarias del issuer (config): CRUD y listado para uso en preview.
Se persiste en DB; los movimientos preview NO.
"""
from __future__ import annotations

from typing import Any, Optional

from database import db, db_rows, table_exists


def list_active_accounts(issuer_id: int) -> list[dict[str, Any]]:
    """Lista cuentas bancarias activas del issuer."""
    if not table_exists(db(), "issuer_bank_accounts"):
        return []
    rows = db_rows(
        """SELECT id, issuer_id, alias, bank_name, clabe, account_last4, holder_name, rfc_titular, is_active, created_at, updated_at
           FROM issuer_bank_accounts WHERE issuer_id = ? AND is_active = 1 ORDER BY alias""",
        (issuer_id,),
    )
    return [dict(r) for r in rows]


def list_all_accounts(issuer_id: int) -> list[dict[str, Any]]:
    """Lista todas las cuentas del issuer (activas e inactivas)."""
    if not table_exists(db(), "issuer_bank_accounts"):
        return []
    rows = db_rows(
        """SELECT id, issuer_id, alias, bank_name, clabe, account_last4, holder_name, rfc_titular, is_active, created_at, updated_at
           FROM issuer_bank_accounts WHERE issuer_id = ? ORDER BY alias""",
        (issuer_id,),
    )
    return [dict(r) for r in rows]


def get_account(account_id: int, issuer_id: int) -> Optional[dict[str, Any]]:
    """Obtiene una cuenta por id si pertenece al issuer."""
    if not table_exists(db(), "issuer_bank_accounts"):
        return None
    rows = db_rows(
        "SELECT id, issuer_id, alias, bank_name, clabe, account_last4, holder_name, rfc_titular, is_active, created_at, updated_at FROM issuer_bank_accounts WHERE id = ? AND issuer_id = ?",
        (account_id, issuer_id),
    )
    return rows[0] if rows else None


def create_account(
    issuer_id: int,
    alias: str,
    bank_name: str,
    clabe: Optional[str] = None,
    account_last4: Optional[str] = None,
    holder_name: Optional[str] = None,
    rfc_titular: Optional[str] = None,
    is_active: bool = True,
) -> dict[str, Any]:
    """Crea una cuenta bancaria. Devuelve el registro creado."""
    conn = db()
    try:
        if not table_exists(conn, "issuer_bank_accounts"):
            return {"id": 0, "error": "Tabla no existe"}
        conn.execute(
            """INSERT INTO issuer_bank_accounts (issuer_id, alias, bank_name, clabe, account_last4, holder_name, rfc_titular, is_active, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
            (
                issuer_id,
                (alias or "").strip() or "Sin alias",
                (bank_name or "").strip() or "Otro",
                (clabe or "").strip() or None,
                (account_last4 or "").strip()[:4] if account_last4 else None,
                (holder_name or "").strip() or None,
                (rfc_titular or "").strip() or None,
                1 if is_active else 0,
            ),
        )
        conn.commit()
        rid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        row = db_rows("SELECT id, issuer_id, alias, bank_name, clabe, account_last4, holder_name, rfc_titular, is_active, created_at, updated_at FROM issuer_bank_accounts WHERE id = ?", (rid,))
        return dict(row[0]) if row else {"id": rid}
    finally:
        conn.close()


def update_account(
    account_id: int,
    issuer_id: int,
    alias: Optional[str] = None,
    bank_name: Optional[str] = None,
    clabe: Optional[str] = None,
    account_last4: Optional[str] = None,
    holder_name: Optional[str] = None,
    rfc_titular: Optional[str] = None,
    is_active: Optional[bool] = None,
) -> Optional[dict[str, Any]]:
    """Actualiza una cuenta. Devuelve el registro actualizado o None si no existe."""
    acc = get_account(account_id, issuer_id)
    if not acc:
        return None
    conn = db()
    try:
        updates = ["updated_at = datetime('now')"]
        params: list[Any] = []
        if alias is not None:
            updates.append("alias = ?")
            params.append((alias or "").strip() or "Sin alias")
        if bank_name is not None:
            updates.append("bank_name = ?")
            params.append((bank_name or "").strip() or "Otro")
        if clabe is not None:
            updates.append("clabe = ?")
            params.append((clabe or "").strip() or None)
        if account_last4 is not None:
            updates.append("account_last4 = ?")
            params.append((account_last4 or "").strip()[:4] if account_last4 else None)
        if holder_name is not None:
            updates.append("holder_name = ?")
            params.append((holder_name or "").strip() or None)
        if rfc_titular is not None:
            updates.append("rfc_titular = ?")
            params.append((rfc_titular or "").strip() or None)
        if is_active is not None:
            updates.append("is_active = ?")
            params.append(1 if is_active else 0)
        if len(params) == 0:
            return acc
        params.extend([account_id, issuer_id])
        conn.execute(f"UPDATE issuer_bank_accounts SET {', '.join(updates)} WHERE id = ? AND issuer_id = ?", params)
        conn.commit()
        return get_account(account_id, issuer_id)
    finally:
        conn.close()


def delete_account(account_id: int, issuer_id: int) -> bool:
    """Elimina una cuenta. Devuelve True si existía."""
    acc = get_account(account_id, issuer_id)
    if not acc:
        return False
    conn = db()
    try:
        conn.execute("DELETE FROM issuer_bank_accounts WHERE id = ? AND issuer_id = ?", (account_id, issuer_id))
        conn.commit()
        return True
    finally:
        conn.close()
