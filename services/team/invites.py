"""Team invite management: create, accept, revoke, list."""

import logging
import secrets
from datetime import datetime, timedelta
from typing import Optional

from database import db, db_rows

logger = logging.getLogger(__name__)

INVITE_EXPIRY_DAYS = 7


def create_invite(
    issuer_id: int,
    invited_by_user_id: int,
    email: str,
    role: str,
) -> dict:
    """Create a new team invitation.

    Args:
        issuer_id: Tenant ID.
        invited_by_user_id: User who is inviting.
        email: Email address of invitee.
        role: Role to assign (accountant, viewer, admin).

    Returns:
        Dict with invite details including token.

    Raises:
        ValueError: If email already has a pending invite or active membership.
    """
    email = email.strip().lower()
    if role not in ("accountant", "viewer", "admin"):
        raise ValueError(f"Rol inválido: {role}")

    conn = db()
    try:
        # Check for existing active membership
        existing = conn.execute(
            """SELECT m.id FROM memberships m
               JOIN users u ON u.id = m.user_id
               WHERE m.issuer_id = ? AND LOWER(u.email) = ?""",
            (issuer_id, email),
        ).fetchone()
        if existing:
            raise ValueError("Este email ya tiene acceso a esta cuenta.")

        # Check for pending invite
        pending = conn.execute(
            """SELECT id FROM membership_invites
               WHERE issuer_id = ? AND LOWER(email) = ? AND status = 'pending'""",
            (issuer_id, email),
        ).fetchone()
        if pending:
            raise ValueError("Ya existe una invitación pendiente para este email.")

        token = secrets.token_urlsafe(32)
        expires_at = (datetime.now() + timedelta(days=INVITE_EXPIRY_DAYS)).isoformat()

        conn.execute(
            """INSERT INTO membership_invites
               (issuer_id, invited_by_user_id, email, role, token, expires_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (issuer_id, invited_by_user_id, email, role, token, expires_at),
        )
        conn.commit()

        return {
            "email": email,
            "role": role,
            "token": token,
            "expires_at": expires_at,
        }
    finally:
        conn.close()


def accept_invite(token: str, user_id: int, user_email: str) -> dict:
    """Accept a team invitation.

    Args:
        token: Invite token.
        user_id: User accepting the invite.
        user_email: Email of the accepting user.

    Returns:
        Dict with issuer_id and role.

    Raises:
        ValueError: If token is invalid, expired, or email mismatch.
    """
    conn = db()
    try:
        invite = conn.execute(
            "SELECT * FROM membership_invites WHERE token = ? AND status = 'pending'",
            (token,),
        ).fetchone()
        if not invite:
            raise ValueError("Invitación no válida o ya usada.")

        if datetime.fromisoformat(invite["expires_at"]) < datetime.now():
            conn.execute(
                "UPDATE membership_invites SET status = 'expired' WHERE id = ?",
                (invite["id"],),
            )
            conn.commit()
            raise ValueError("La invitación expiró.")

        if user_email.strip().lower() != invite["email"].strip().lower():
            raise ValueError("El email no coincide con la invitación.")

        # Create membership
        conn.execute(
            """INSERT OR IGNORE INTO memberships (user_id, issuer_id, role)
               VALUES (?, ?, ?)""",
            (user_id, invite["issuer_id"], invite["role"]),
        )

        # Mark invite as accepted
        conn.execute(
            """UPDATE membership_invites
               SET status = 'accepted', accepted_at = datetime('now'), accepted_by_user_id = ?
               WHERE id = ?""",
            (user_id, invite["id"]),
        )
        conn.commit()

        return {
            "issuer_id": invite["issuer_id"],
            "role": invite["role"],
        }
    finally:
        conn.close()


def revoke_invite(invite_id: int, issuer_id: int) -> bool:
    """Revoke a pending invitation.

    Args:
        invite_id: ID of the invite.
        issuer_id: Tenant ID (for authorization).

    Returns:
        True if revoked, False if not found.
    """
    conn = db()
    try:
        result = conn.execute(
            """UPDATE membership_invites
               SET status = 'revoked'
               WHERE id = ? AND issuer_id = ? AND status = 'pending'""",
            (invite_id, issuer_id),
        )
        conn.commit()
        return result.rowcount > 0
    finally:
        conn.close()


def list_invites(issuer_id: int, status: Optional[str] = "pending") -> list[dict]:
    """List invitations for an issuer.

    Args:
        issuer_id: Tenant ID.
        status: Filter by status (default: 'pending'). None for all.

    Returns:
        List of invite dicts.
    """
    if status:
        return db_rows(
            """SELECT id, email, role, status, created_at, expires_at
               FROM membership_invites
               WHERE issuer_id = ? AND status = ?
               ORDER BY created_at DESC""",
            (issuer_id, status),
        )
    return db_rows(
        """SELECT id, email, role, status, created_at, expires_at
           FROM membership_invites
           WHERE issuer_id = ?
           ORDER BY created_at DESC""",
        (issuer_id,),
    )
