"""Team member management: list, change role, remove."""

import logging
from typing import Optional

from database import db, db_rows

logger = logging.getLogger(__name__)


def list_members(issuer_id: int) -> list[dict]:
    """List all team members for an issuer.

    Args:
        issuer_id: Tenant ID.

    Returns:
        List of member dicts with user_id, email, role, joined_at.
    """
    return db_rows(
        """SELECT m.user_id, u.email, m.role,
                  m.created_at AS joined_at
           FROM memberships m
           JOIN users u ON u.id = m.user_id
           WHERE m.issuer_id = ?
           ORDER BY
             CASE m.role WHEN 'owner' THEN 0 WHEN 'admin' THEN 1
                         WHEN 'accountant' THEN 2 ELSE 3 END,
             u.email""",
        (issuer_id,),
    )


def change_role(
    issuer_id: int,
    target_user_id: int,
    new_role: str,
    acting_user_id: int,
) -> bool:
    """Change a member's role.

    Args:
        issuer_id: Tenant ID.
        target_user_id: User whose role to change.
        new_role: New role to assign.
        acting_user_id: User performing the change (must be owner).

    Returns:
        True if updated.

    Raises:
        ValueError: If trying to change own role or invalid role.
    """
    if new_role not in ("viewer", "accountant", "admin"):
        raise ValueError(f"Rol inválido: {new_role}")
    if target_user_id == acting_user_id:
        raise ValueError("No puedes cambiar tu propio rol.")

    conn = db()
    try:
        # Cannot change owner role
        current = conn.execute(
            "SELECT role FROM memberships WHERE issuer_id = ? AND user_id = ?",
            (issuer_id, target_user_id),
        ).fetchone()
        if not current:
            raise ValueError("Miembro no encontrado.")
        if current["role"] == "owner":
            raise ValueError("No se puede cambiar el rol del propietario.")

        conn.execute(
            "UPDATE memberships SET role = ? WHERE issuer_id = ? AND user_id = ?",
            (new_role, issuer_id, target_user_id),
        )
        conn.commit()
        return True
    finally:
        conn.close()


def remove_member(
    issuer_id: int,
    target_user_id: int,
    acting_user_id: int,
) -> bool:
    """Remove a member from the team.

    Args:
        issuer_id: Tenant ID.
        target_user_id: User to remove.
        acting_user_id: User performing removal (must be owner).

    Returns:
        True if removed.

    Raises:
        ValueError: If trying to remove self or owner.
    """
    if target_user_id == acting_user_id:
        raise ValueError("No puedes eliminarte a ti mismo.")

    conn = db()
    try:
        current = conn.execute(
            "SELECT role FROM memberships WHERE issuer_id = ? AND user_id = ?",
            (issuer_id, target_user_id),
        ).fetchone()
        if not current:
            raise ValueError("Miembro no encontrado.")
        if current["role"] == "owner":
            raise ValueError("No se puede eliminar al propietario.")

        conn.execute(
            "DELETE FROM memberships WHERE issuer_id = ? AND user_id = ?",
            (issuer_id, target_user_id),
        )
        conn.commit()
        return True
    finally:
        conn.close()
