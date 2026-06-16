"""Team management UI: members list, invites, role changes."""

import logging

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from routers.deps import get_portal_issuer
from routers.portal._helpers import render_portal
from services.action_log import log_action
from services.team.invites import create_invite, list_invites, revoke_invite
from services.team.members import change_role, list_members, remove_member
from services.team.permissions import ROLE_LABELS, has_permission

logger = logging.getLogger(__name__)


def register_team_routes(router: APIRouter, templates):
    """Register /portal/team routes."""

    @router.get("/team")
    async def portal_team(request: Request, issuer: dict = Depends(get_portal_issuer)):
        role = getattr(request.state, "membership_role", "")
        if not has_permission(role, "invite_member"):
            raise HTTPException(403, detail="No tienes permiso para gestionar el equipo.")

        issuer_id = issuer["id"]
        members = list_members(issuer_id)
        invites = list_invites(issuer_id, status="pending")

        return render_portal(
            templates,
            request,
            issuer=issuer,
            template_name="portal_team.html",
            active_page="team",
            title="Equipo",
            members=members,
            invites=invites,
            role_labels=ROLE_LABELS,
            user_role=role,
        )

    @router.post("/team/invite")
    async def portal_team_invite(
        request: Request,
        payload: dict = Body(...),
        issuer: dict = Depends(get_portal_issuer),
    ):
        role = getattr(request.state, "membership_role", "")
        if not has_permission(role, "invite_member"):
            return JSONResponse({"ok": False, "detail": "Sin permiso."}, status_code=403)

        email = (payload.get("email") or "").strip().lower()
        invite_role = (payload.get("role") or "").strip()

        if not email or "@" not in email:
            return JSONResponse({"ok": False, "detail": "Email inválido."}, status_code=400)

        user_id = getattr(request.state, "user_id", 0)
        try:
            result = create_invite(
                issuer_id=issuer["id"],
                invited_by_user_id=user_id,
                email=email,
                role=invite_role,
            )
            log_action(request, "team_invite_created",
                       issuer_id=issuer["id"], invited_email=email, role=invite_role)
            return JSONResponse({"ok": True, "data": result})
        except ValueError as e:
            return JSONResponse({"ok": False, "detail": str(e)}, status_code=400)

    @router.post("/team/invites/{invite_id}/revoke")
    async def portal_team_revoke_invite(
        request: Request,
        invite_id: int,
        issuer: dict = Depends(get_portal_issuer),
    ):
        role = getattr(request.state, "membership_role", "")
        if not has_permission(role, "invite_member"):
            return JSONResponse({"ok": False, "detail": "Sin permiso."}, status_code=403)

        revoked = revoke_invite(invite_id, issuer["id"])
        if revoked:
            log_action(request, "team_invite_revoked",
                       issuer_id=issuer["id"], invite_id=invite_id)
        return JSONResponse({"ok": revoked})

    @router.post("/team/members/{user_id}/role")
    async def portal_team_change_role(
        request: Request,
        user_id: int,
        payload: dict = Body(...),
        issuer: dict = Depends(get_portal_issuer),
    ):
        role = getattr(request.state, "membership_role", "")
        if not has_permission(role, "change_member_role"):
            return JSONResponse({"ok": False, "detail": "Solo el propietario puede cambiar roles."}, status_code=403)

        new_role = (payload.get("role") or "").strip()
        acting_user_id = getattr(request.state, "user_id", 0)
        try:
            change_role(issuer["id"], user_id, new_role, acting_user_id)
            log_action(request, "team_role_changed",
                       issuer_id=issuer["id"], target_user_id=user_id, new_role=new_role)
            return JSONResponse({"ok": True})
        except ValueError as e:
            return JSONResponse({"ok": False, "detail": str(e)}, status_code=400)

    @router.post("/team/members/{user_id}/remove")
    async def portal_team_remove_member(
        request: Request,
        user_id: int,
        issuer: dict = Depends(get_portal_issuer),
    ):
        role = getattr(request.state, "membership_role", "")
        if not has_permission(role, "remove_member"):
            return JSONResponse({"ok": False, "detail": "Solo el propietario puede eliminar miembros."}, status_code=403)

        acting_user_id = getattr(request.state, "user_id", 0)
        try:
            remove_member(issuer["id"], user_id, acting_user_id)
            log_action(request, "team_member_removed",
                       issuer_id=issuer["id"], removed_user_id=user_id)
            return JSONResponse({"ok": True})
        except ValueError as e:
            return JSONResponse({"ok": False, "detail": str(e)}, status_code=400)
