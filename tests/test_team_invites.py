"""Tests for team invites and permissions (Phase 4)."""

import pytest

from database import db
from services.team.invites import accept_invite, create_invite, list_invites, revoke_invite
from services.team.permissions import ROLE_ORDER, has_permission

ISSUER_ID = 99904
OWNER_USER_ID = 99904
VIEWER_USER_ID = 99905


@pytest.fixture(scope="module", autouse=True)
def seed():
    """Create test issuer and users for team tests."""
    conn = db()
    # Create membership_invites table if not yet migrated
    conn.execute(
        """CREATE TABLE IF NOT EXISTS membership_invites (
           id INTEGER PRIMARY KEY AUTOINCREMENT,
           issuer_id INTEGER NOT NULL,
           invited_by_user_id INTEGER NOT NULL,
           email TEXT NOT NULL,
           role TEXT NOT NULL,
           token TEXT NOT NULL UNIQUE,
           expires_at TEXT NOT NULL,
           accepted_at TEXT,
           accepted_by_user_id INTEGER,
           status TEXT NOT NULL DEFAULT 'pending',
           created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )"""
    )
    # Clean up stale data from prior runs
    conn.execute("DELETE FROM membership_invites WHERE issuer_id = ?", (ISSUER_ID,))
    conn.execute(
        "DELETE FROM memberships WHERE issuer_id = ? AND user_id != ?",
        (ISSUER_ID, OWNER_USER_ID),
    )
    conn.execute(
        """INSERT OR IGNORE INTO issuers (id, rfc, razon_social, active, regimen_fiscal)
           VALUES (?, 'XTEAM0101AAA', 'Team Test SA', 1, '601')""",
        (ISSUER_ID,),
    )
    conn.execute(
        """INSERT OR IGNORE INTO users (id, email, password_hash)
           VALUES (?, 'owner@team.test', 'x')""",
        (OWNER_USER_ID,),
    )
    conn.execute(
        """INSERT OR IGNORE INTO users (id, email, password_hash)
           VALUES (?, 'viewer@team.test', 'x')""",
        (VIEWER_USER_ID,),
    )
    conn.execute(
        """INSERT OR IGNORE INTO memberships (user_id, issuer_id, role)
           VALUES (?, ?, 'owner')""",
        (OWNER_USER_ID, ISSUER_ID),
    )
    conn.commit()
    conn.close()
    yield


# --- Permissions ---

def test_permission_owner_can_do_everything():
    """Owner role should have all permissions."""
    for action in ("view_invoices", "issue_invoice", "cancel_invoice",
                   "edit_issuer_settings", "invite_member", "upload_fiel",
                   "manage_billing", "remove_member"):
        assert has_permission("owner", action), f"owner should have {action}"


def test_permission_viewer_can_only_view():
    """Viewer should only have view_invoices."""
    assert has_permission("viewer", "view_invoices")
    assert not has_permission("viewer", "issue_invoice")
    assert not has_permission("viewer", "edit_issuer_settings")


def test_permission_accountant_can_issue():
    """Accountant should be able to issue invoices."""
    assert has_permission("accountant", "issue_invoice")
    assert has_permission("accountant", "cancel_invoice")
    assert not has_permission("accountant", "edit_issuer_settings")


def test_permission_admin_can_manage():
    """Admin should be able to manage settings and invite."""
    assert has_permission("admin", "edit_issuer_settings")
    assert has_permission("admin", "invite_member")
    assert not has_permission("admin", "upload_fiel")


def test_role_hierarchy():
    """Role hierarchy should be viewer < accountant < admin < owner."""
    assert ROLE_ORDER["viewer"] < ROLE_ORDER["accountant"]
    assert ROLE_ORDER["accountant"] < ROLE_ORDER["admin"]
    assert ROLE_ORDER["admin"] < ROLE_ORDER["owner"]


# --- Invites ---

def test_create_invite_succeeds():
    """Creating an invite should return a token."""
    result = create_invite(
        issuer_id=ISSUER_ID,
        invited_by_user_id=OWNER_USER_ID,
        email="newuser@team.test",
        role="accountant",
    )
    assert result["token"]
    assert result["role"] == "accountant"
    assert result["email"] == "newuser@team.test"


def test_create_invite_rejects_duplicate_pending():
    """Should reject duplicate pending invite for same email."""
    with pytest.raises(ValueError, match="pendiente"):
        create_invite(
            issuer_id=ISSUER_ID,
            invited_by_user_id=OWNER_USER_ID,
            email="newuser@team.test",
            role="viewer",
        )


def test_create_invite_rejects_existing_member():
    """Should reject invite for email with existing membership."""
    with pytest.raises(ValueError, match="ya tiene acceso"):
        create_invite(
            issuer_id=ISSUER_ID,
            invited_by_user_id=OWNER_USER_ID,
            email="owner@team.test",
            role="viewer",
        )


def test_create_invite_rejects_invalid_role():
    """Should reject invite with invalid role."""
    with pytest.raises(ValueError, match="inválido"):
        create_invite(
            issuer_id=ISSUER_ID,
            invited_by_user_id=OWNER_USER_ID,
            email="bad@team.test",
            role="superadmin",
        )


def test_list_invites_returns_pending():
    """list_invites should return pending invitations."""
    invites = list_invites(ISSUER_ID)
    assert len(invites) >= 1
    assert any(i["email"] == "newuser@team.test" for i in invites)


def test_accept_invite_succeeds():
    """Accepting an invite should create a membership."""
    # Create a fresh invite
    result = create_invite(
        issuer_id=ISSUER_ID,
        invited_by_user_id=OWNER_USER_ID,
        email="viewer@team.test",
        role="viewer",
    )
    # Accept it
    accepted = accept_invite(result["token"], VIEWER_USER_ID, "viewer@team.test")
    assert accepted["issuer_id"] == ISSUER_ID
    assert accepted["role"] == "viewer"


def test_accept_invite_rejects_email_mismatch():
    """Should reject if accepting user's email doesn't match."""
    result = create_invite(
        issuer_id=ISSUER_ID,
        invited_by_user_id=OWNER_USER_ID,
        email="mismatch@team.test",
        role="viewer",
    )
    with pytest.raises(ValueError, match="no coincide"):
        accept_invite(result["token"], VIEWER_USER_ID, "wrong@team.test")


def test_revoke_invite_succeeds():
    """Revoking a pending invite should work."""
    result = create_invite(
        issuer_id=ISSUER_ID,
        invited_by_user_id=OWNER_USER_ID,
        email="revoke@team.test",
        role="accountant",
    )
    # Get the invite ID
    invites = list_invites(ISSUER_ID)
    invite = next(i for i in invites if i["email"] == "revoke@team.test")
    assert revoke_invite(invite["id"], ISSUER_ID) is True


# --- Route test ---

def test_team_page_returns_200_for_owner():
    """GET /portal/team should return 200 for owner."""
    from fastapi.testclient import TestClient

    from app import app
    from tests.helpers import make_session_cookie

    c = TestClient(app)
    cookies = make_session_cookie(ISSUER_ID, OWNER_USER_ID)
    for k, v in cookies.items():
        c.cookies.set(k, v)
    resp = c.get("/portal/team")
    assert resp.status_code == 200
    assert "Equipo" in resp.text or "equipo" in resp.text.lower()
