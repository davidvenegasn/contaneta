"""Persist and retrieve per-org Facturapi API keys encrypted at rest.

Each Facturapi organization has its own test/live API key for CFDI emission.
These are distinct from the account-level User Secret Key which only manages
organizations. Keys are stored AES-GCM encrypted in issuers table columns.
"""
from __future__ import annotations

import logging

from database import db
from services.sat.crypto_at_rest import decrypt_text, encrypt_text

logger = logging.getLogger(__name__)


def save_org_keys(
    issuer_id: int,
    *,
    test_key: str | None = None,
    live_key: str | None = None,
) -> None:
    """Encrypt and persist org API keys for an issuer.

    Args:
        issuer_id: Tenant ID.
        test_key: sk_test_... key (optional).
        live_key: sk_live_... key (optional).
    """
    sets: list[str] = []
    params: list = []
    if test_key:
        sets.append("facturapi_test_key_encrypted = ?")
        params.append(encrypt_text(issuer_id=issuer_id, plaintext=test_key))
    if live_key:
        sets.append("facturapi_live_key_encrypted = ?")
        params.append(encrypt_text(issuer_id=issuer_id, plaintext=live_key))
    if not sets:
        return
    sets.append("facturapi_keys_fetched_at = datetime('now')")
    params.append(issuer_id)
    conn = db()
    try:
        conn.execute(
            f"UPDATE issuers SET {', '.join(sets)} WHERE id = ?",
            tuple(params),
        )
        conn.commit()
    finally:
        conn.close()
    logger.info("Saved org API keys for issuer=%s", issuer_id)


def load_org_key(issuer_id: int, *, mode: str = "test") -> str | None:
    """Load and decrypt an org API key for the given issuer.

    Args:
        issuer_id: Tenant ID.
        mode: 'test' or 'live'.

    Returns:
        Decrypted key string, or None if not stored.
    """
    col = "facturapi_test_key_encrypted" if mode == "test" else "facturapi_live_key_encrypted"
    conn = db()
    try:
        row = conn.execute(
            f"SELECT {col} FROM issuers WHERE id = ? LIMIT 1",
            (issuer_id,),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    enc = row[col]
    if not enc:
        return None
    return decrypt_text(issuer_id=issuer_id, token=enc)
