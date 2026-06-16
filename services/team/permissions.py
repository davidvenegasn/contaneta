"""Role-based permission checks.

Hierarchy: viewer < accountant < admin < owner
"""

ROLE_ORDER = {"viewer": 0, "accountant": 1, "admin": 2, "owner": 3}

ACTION_REQUIREMENTS = {
    "view_invoices": "viewer",
    "issue_invoice": "accountant",
    "cancel_invoice": "accountant",
    "create_quotation": "accountant",
    "upload_declarations": "accountant",
    "edit_issuer_settings": "admin",
    "view_audit_log": "admin",
    "invite_member": "admin",
    "upload_fiel": "owner",
    "upload_csd": "owner",
    "manage_billing": "owner",
    "remove_member": "owner",
    "change_member_role": "owner",
}

# Human-readable role labels (Spanish)
ROLE_LABELS = {
    "viewer": "Solo lectura",
    "accountant": "Contador",
    "admin": "Administrador",
    "owner": "Propietario",
}


def has_permission(user_role: str, action: str) -> bool:
    """Check if a role has permission for an action.

    Args:
        user_role: User's role (viewer, accountant, admin, owner).
        action: Action key from ACTION_REQUIREMENTS.

    Returns:
        True if the role has sufficient privileges.
    """
    required = ACTION_REQUIREMENTS.get(action, "owner")
    return ROLE_ORDER.get(user_role, -1) >= ROLE_ORDER.get(required, 99)


def require_role(min_role: str):
    """FastAPI dependency that checks minimum role.

    Usage:
        @router.post("/some-route", dependencies=[Depends(require_role("admin"))])
    """
    from fastapi import HTTPException, Request

    def checker(request: Request):
        role = getattr(request.state, "membership_role", "viewer")
        if ROLE_ORDER.get(role, -1) < ROLE_ORDER.get(min_role, 99):
            raise HTTPException(
                status_code=403,
                detail=f"Tu rol ({ROLE_LABELS.get(role, role)}) no permite esta acción.",
            )

    return checker
