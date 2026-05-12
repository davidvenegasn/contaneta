"""Portal settings routes — user profile, password change, issuer fiscal data."""
import logging

from fastapi import Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from config import REGIMEN_CODE_DESCRIPTIONS
from routers.deps import get_portal_issuer
from routers.portal._helpers import render_portal
from services.auth import csrf as csrf_service
from services.auth import users as users_service
from services import issuers as issuers_service

logger = logging.getLogger(__name__)


def register_settings_routes(router, templates):
    """Register /portal/settings/* routes on the portal router."""

    def _render(request, **kwargs):
        return render_portal(templates, request, **kwargs)

    @router.get("/settings", response_class=HTMLResponse)
    def portal_settings(
        request: Request,
        issuer: dict = Depends(get_portal_issuer),
        success: str = "",
        error: str = "",
    ):
        """Render the settings page with user profile, password, and issuer data sections."""
        user_id = getattr(request.state, "user_id", None) or 0
        user = users_service.get_user_by_id(user_id) if user_id else None
        membership_role = getattr(request.state, "membership_role", "viewer")
        return _render(
            request,
            issuer=issuer,
            template_name="portal_settings.html",
            active_page="settings",
            title="Configuración",
            extra={
                "user": user,
                "membership_role": membership_role,
                "regimen_options": REGIMEN_CODE_DESCRIPTIONS,
                "success_msg": success,
                "error_msg": error,
            },
        )

    @router.post("/settings/profile", response_class=RedirectResponse)
    def portal_settings_update_profile(
        request: Request,
        issuer: dict = Depends(get_portal_issuer),
        csrf_token: str = Form(""),
        name: str = Form(""),
        email: str = Form(""),
    ):
        """Update user name and email."""
        if not csrf_service.verify_csrf_token(csrf_token):
            raise HTTPException(status_code=403, detail="Token CSRF inválido o expirado")
        user_id = getattr(request.state, "user_id", None) or 0
        if not user_id:
            raise HTTPException(status_code=401, detail="Sesión inválida")
        try:
            name_val = name.strip()
            email_val = email.strip().lower()
            if not email_val:
                return RedirectResponse(
                    url="/portal/settings?error=El+correo+es+obligatorio",
                    status_code=302,
                )
            users_service.update_user_name(user_id, name_val)
            users_service.update_user_email(user_id, email_val)
        except ValueError as exc:
            msg = str(exc).replace(" ", "+")
            return RedirectResponse(url=f"/portal/settings?error={msg}", status_code=302)
        return RedirectResponse(url="/portal/settings?success=Perfil+actualizado", status_code=302)

    @router.post("/settings/password", response_class=RedirectResponse)
    def portal_settings_change_password(
        request: Request,
        issuer: dict = Depends(get_portal_issuer),
        csrf_token: str = Form(""),
        current_password: str = Form(""),
        new_password: str = Form(""),
        confirm_password: str = Form(""),
    ):
        """Change user password (requires current password verification)."""
        if not csrf_service.verify_csrf_token(csrf_token):
            raise HTTPException(status_code=403, detail="Token CSRF inválido o expirado")
        user_id = getattr(request.state, "user_id", None) or 0
        if not user_id:
            raise HTTPException(status_code=401, detail="Sesión inválida")

        if not current_password or not new_password:
            return RedirectResponse(
                url="/portal/settings?error=Todos+los+campos+de+contraseña+son+obligatorios",
                status_code=302,
            )
        if new_password != confirm_password:
            return RedirectResponse(
                url="/portal/settings?error=Las+contraseñas+no+coinciden",
                status_code=302,
            )
        strength_err = users_service.validate_password_strength(new_password)
        if strength_err:
            msg = strength_err.replace(" ", "+")
            return RedirectResponse(url=f"/portal/settings?error={msg}", status_code=302)

        existing_hash = users_service.get_user_password_hash(user_id)
        if not users_service.verify_password(current_password, existing_hash):
            return RedirectResponse(
                url="/portal/settings?error=La+contraseña+actual+es+incorrecta",
                status_code=302,
            )

        new_hash = users_service.hash_password(new_password)
        users_service.update_user_password(user_id, new_hash)
        return RedirectResponse(
            url="/portal/settings?success=Contraseña+actualizada",
            status_code=302,
        )

    @router.post("/settings/issuer", response_class=RedirectResponse)
    def portal_settings_update_issuer(
        request: Request,
        issuer: dict = Depends(get_portal_issuer),
        csrf_token: str = Form(""),
        razon_social: str = Form(""),
        regimen_fiscal: str = Form(""),
    ):
        """Update issuer fiscal data (razon social and regimen fiscal)."""
        if not csrf_service.verify_csrf_token(csrf_token):
            raise HTTPException(status_code=403, detail="Token CSRF inválido o expirado")
        membership_role = getattr(request.state, "membership_role", "viewer")
        if membership_role not in ("owner", "admin"):
            return RedirectResponse(
                url="/portal/settings?error=No+tienes+permisos+para+editar+datos+fiscales",
                status_code=302,
            )
        issuer_id = int(issuer.get("id") or 0)
        if issuer_id <= 0:
            raise HTTPException(status_code=401, detail="Sesión inválida")

        razon_val = razon_social.strip()
        regimen_val = regimen_fiscal.strip()
        if regimen_val and regimen_val not in REGIMEN_CODE_DESCRIPTIONS:
            return RedirectResponse(
                url="/portal/settings?error=Régimen+fiscal+inválido",
                status_code=302,
            )

        issuers_service.update_issuer_profile(
            issuer_id,
            razon_social=razon_val if razon_val else None,
            regimen_fiscal=regimen_val if regimen_val else None,
        )
        return RedirectResponse(
            url="/portal/settings?success=Datos+fiscales+actualizados",
            status_code=302,
        )
