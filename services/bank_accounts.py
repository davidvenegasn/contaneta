"""
Cuentas bancarias del issuer (config): CRUD y listado para uso en preview.
Se persiste en DB; los movimientos preview NO.

Security: CLABE is encrypted at rest when crypto is available.
The `clabe` column stores either an encrypted token (enc:v1:...) or plain text (legacy/dev).
`account_last4` always stores the last 4 digits in plain text for display.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from database import db, db_rows, table_exists

logger = logging.getLogger(__name__)


def _encrypt_clabe(issuer_id: int, clabe_plain: str) -> str:
    """Encrypt CLABE for storage. Falls back to plain text if crypto unavailable."""
    try:
        from services.crypto_at_rest import encrypt_text
        return encrypt_text(issuer_id=issuer_id, plaintext=clabe_plain)
    except Exception:
        return clabe_plain


def decrypt_clabe(issuer_id: int, clabe_stored: str) -> str:
    """Decrypt CLABE from storage. Returns as-is if not encrypted or crypto unavailable."""
    if not clabe_stored:
        return ""
    if not clabe_stored.startswith("enc:"):
        return clabe_stored
    try:
        from services.crypto_at_rest import decrypt_text
        return decrypt_text(issuer_id=issuer_id, token=clabe_stored)
    except Exception:
        logger.warning("Failed to decrypt CLABE for issuer %s, returning masked", issuer_id)
        return "****"


def _extract_last4(clabe: str | None) -> str | None:
    """Extract last 4 digits from a CLABE string."""
    if not clabe:
        return None
    digits = "".join(c for c in clabe if c.isdigit())
    return digits[-4:] if len(digits) >= 4 else None


def _prepare_clabe_for_storage(issuer_id: int, clabe_raw: str | None, account_last4: str | None) -> tuple[str | None, str | None]:
    """
    Prepare CLABE and last4 for DB storage.
    Returns (clabe_to_store, last4_to_store).
    """
    clabe_clean = (clabe_raw or "").strip() or None
    if clabe_clean:
        last4 = _extract_last4(clabe_clean) or (account_last4 or "").strip()[:4] or None
        clabe_encrypted = _encrypt_clabe(issuer_id, clabe_clean)
        return clabe_encrypted, last4
    last4 = (account_last4 or "").strip()[:4] if account_last4 else None
    return None, last4


def _mask_clabe_in_row(row: dict[str, Any]) -> dict[str, Any]:
    """Replace full CLABE with masked version for UI display. Internal use gets decrypt_clabe()."""
    d = dict(row)
    clabe = d.get("clabe") or ""
    if clabe:
        # Never expose full CLABE (encrypted or plain) to UI
        last4 = d.get("account_last4") or _extract_last4(clabe) or "****"
        d["clabe"] = f"****{last4}" if last4 else "****"
    return d


def list_active_accounts(issuer_id: int) -> list[dict[str, Any]]:
    """Lista cuentas bancarias activas del issuer. CLABE is masked."""
    if not table_exists(db(), "issuer_bank_accounts"):
        return []
    rows = db_rows(
        """SELECT id, issuer_id, alias, bank_name, clabe, account_last4, holder_name, rfc_titular, is_active, created_at, updated_at
           FROM issuer_bank_accounts WHERE issuer_id = ? AND is_active = 1 ORDER BY alias""",
        (issuer_id,),
    )
    return [_mask_clabe_in_row(r) for r in rows]


def list_active_accounts_raw(issuer_id: int) -> list[dict[str, Any]]:
    """Lista cuentas con CLABE descifrado — solo para uso interno (matching, classification)."""
    if not table_exists(db(), "issuer_bank_accounts"):
        return []
    rows = db_rows(
        """SELECT id, issuer_id, alias, bank_name, clabe, account_last4, holder_name, rfc_titular, is_active, created_at, updated_at
           FROM issuer_bank_accounts WHERE issuer_id = ? AND is_active = 1 ORDER BY alias""",
        (issuer_id,),
    )
    result = []
    for r in rows:
        d = dict(r)
        stored = d.get("clabe") or ""
        if stored:
            d["clabe"] = decrypt_clabe(issuer_id, stored)
        result.append(d)
    return result


def list_all_accounts(issuer_id: int) -> list[dict[str, Any]]:
    """Lista todas las cuentas del issuer (activas e inactivas). CLABE is masked."""
    if not table_exists(db(), "issuer_bank_accounts"):
        return []
    rows = db_rows(
        """SELECT id, issuer_id, alias, bank_name, clabe, account_last4, holder_name, rfc_titular, is_active, created_at, updated_at
           FROM issuer_bank_accounts WHERE issuer_id = ? ORDER BY alias""",
        (issuer_id,),
    )
    return [_mask_clabe_in_row(r) for r in rows]


def get_account(account_id: int, issuer_id: int) -> Optional[dict[str, Any]]:
    """Obtiene una cuenta por id si pertenece al issuer. CLABE is masked."""
    if not table_exists(db(), "issuer_bank_accounts"):
        return None
    rows = db_rows(
        "SELECT id, issuer_id, alias, bank_name, clabe, account_last4, holder_name, rfc_titular, is_active, created_at, updated_at FROM issuer_bank_accounts WHERE id = ? AND issuer_id = ?",
        (account_id, issuer_id),
    )
    return _mask_clabe_in_row(rows[0]) if rows else None


def get_account_raw(account_id: int, issuer_id: int) -> Optional[dict[str, Any]]:
    """Obtiene una cuenta con CLABE descifrado — solo para uso interno (validation, ingest)."""
    if not table_exists(db(), "issuer_bank_accounts"):
        return None
    rows = db_rows(
        "SELECT id, issuer_id, alias, bank_name, clabe, account_last4, holder_name, rfc_titular, is_active, created_at, updated_at FROM issuer_bank_accounts WHERE id = ? AND issuer_id = ?",
        (account_id, issuer_id),
    )
    if not rows:
        return None
    d = dict(rows[0])
    stored = d.get("clabe") or ""
    if stored:
        d["clabe"] = decrypt_clabe(issuer_id, stored)
    return d


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
    """Crea una cuenta bancaria. CLABE is encrypted. Devuelve el registro creado."""
    conn = db()
    try:
        if not table_exists(conn, "issuer_bank_accounts"):
            return {"id": 0, "error": "Tabla no existe"}
        clabe_store, last4_store = _prepare_clabe_for_storage(issuer_id, clabe, account_last4)
        conn.execute(
            """INSERT INTO issuer_bank_accounts (issuer_id, alias, bank_name, clabe, account_last4, holder_name, rfc_titular, is_active, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
            (
                issuer_id,
                (alias or "").strip() or "Sin alias",
                (bank_name or "").strip() or "Otro",
                clabe_store,
                last4_store,
                (holder_name or "").strip() or None,
                (rfc_titular or "").strip() or None,
                1 if is_active else 0,
            ),
        )
        conn.commit()
        rid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        row = db_rows(
            "SELECT id, issuer_id, alias, bank_name, clabe, account_last4, holder_name, rfc_titular, is_active, created_at, updated_at FROM issuer_bank_accounts WHERE id = ? AND issuer_id = ?",
            (rid, issuer_id),
        )
        return _mask_clabe_in_row(row[0]) if row else {"id": rid}
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
    """Actualiza una cuenta. CLABE is encrypted. Devuelve el registro actualizado o None si no existe."""
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
            clabe_store, last4_store = _prepare_clabe_for_storage(issuer_id, clabe, account_last4)
            updates.append("clabe = ?")
            params.append(clabe_store)
            # Also update last4 from new CLABE
            updates.append("account_last4 = ?")
            params.append(last4_store)
        elif account_last4 is not None:
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
