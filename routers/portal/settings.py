"""Portal settings routes — user profile, password change, issuer fiscal data, account deletion."""
import logging

from fastapi import Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from config import REGIMEN_CODE_DESCRIPTIONS
from database import db, db_rows, table_exists
from routers.deps import get_portal_issuer
from routers.portal._helpers import render_portal
from services.auth import csrf as csrf_service
from services.auth import session as session_service
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
        from database import db_rows
        issuer_id = int(issuer.get("id") or 0)
        fiel_rows = db_rows(
            "SELECT validation_ok FROM sat_credentials WHERE issuer_id = ? LIMIT 1",
            (issuer_id,),
        )
        sat_status = {
            "configured": bool(fiel_rows),
            "validated": bool(fiel_rows and fiel_rows[0].get("validation_ok")),
        }
        fiel_data: dict = {}
        if sat_status["configured"]:
            from services.sat.sat_credentials_secure import extract_fiel_subject
            fiel_data = extract_fiel_subject(issuer_id)

        # Facturapi lifecycle state for the 3-card credentials view.
        facturapi_state: dict = {
            "org_id": None,
            "provisioned_at": None,
            "manifest_signed_at": None,
            "csd_uploaded_at": None,
            "onboarding_completed_at": None,
            "ciec_configured": False,
        }
        fpi_rows = db_rows(
            """SELECT facturapi_org_id, facturapi_provisioned_at,
                      manifest_signed_at, csd_uploaded_at, onboarding_completed_at
               FROM issuers WHERE id = ? LIMIT 1""",
            (issuer_id,),
        )
        if fpi_rows:
            r = fpi_rows[0]
            facturapi_state.update({
                "org_id": r.get("facturapi_org_id"),
                "provisioned_at": r.get("facturapi_provisioned_at"),
                "manifest_signed_at": r.get("manifest_signed_at"),
                "csd_uploaded_at": r.get("csd_uploaded_at"),
                "onboarding_completed_at": r.get("onboarding_completed_at"),
            })
        ciec_rows = db_rows(
            "SELECT ciec_password_encrypted FROM sat_credentials WHERE issuer_id = ? LIMIT 1",
            (issuer_id,),
        )
        if ciec_rows and ciec_rows[0].get("ciec_password_encrypted"):
            facturapi_state["ciec_configured"] = True
        # Check for pending deletion request
        deletion_pending = None
        if user_id:
            del_rows = db_rows(
                "SELECT scheduled_for FROM account_deletion_requests WHERE user_id = ? AND status = 'pending' LIMIT 1",
                (user_id,),
            )
            if del_rows:
                deletion_pending = del_rows[0].get("scheduled_for")
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
                "sat_status": sat_status,
                "fiel_data": fiel_data,
                "facturapi_state": facturapi_state,
                "deletion_pending": deletion_pending,
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

    # ---------- Account deletion (LFPDPPP) ----------

    @router.post("/settings/delete-account", response_class=RedirectResponse)
    def portal_delete_account(
        request: Request,
        issuer: dict = Depends(get_portal_issuer),
        csrf_token: str = Form(""),
        confirm_text: str = Form(""),
    ):
        """Request account deletion with 30-day grace period (LFPDPPP compliance).

        User must type 'ELIMINAR' to confirm. Creates a pending request in
        account_deletion_requests, logs the user out.

        TODO: scripts/process_deletion_queue.py — cron job to actually delete
        accounts after the 30-day grace period has passed.
        """
        if not csrf_service.verify_csrf_token(csrf_token):
            raise HTTPException(status_code=403, detail="Token CSRF inválido o expirado")
        user_id = getattr(request.state, "user_id", None) or 0
        if not user_id:
            raise HTTPException(status_code=401, detail="Sesión inválida")
        if confirm_text.strip() != "ELIMINAR":
            return RedirectResponse(
                url="/portal/settings?error=Escribe+ELIMINAR+para+confirmar",
                status_code=302,
            )
        conn = db()
        try:
            if not table_exists(conn, "account_deletion_requests"):
                raise HTTPException(status_code=500, detail="Tabla de solicitudes no disponible")
            # Check for existing pending request
            existing = conn.execute(
                "SELECT id FROM account_deletion_requests WHERE user_id = ? AND status = 'pending' LIMIT 1",
                (user_id,),
            ).fetchone()
            if existing:
                return RedirectResponse(
                    url="/portal/settings?error=Ya+existe+una+solicitud+de+eliminación+pendiente",
                    status_code=302,
                )
            conn.execute(
                """INSERT INTO account_deletion_requests (user_id, status, requested_at, scheduled_for)
                   VALUES (?, 'pending', datetime('now'), datetime('now', '+30 days'))""",
                (user_id,),
            )
            conn.commit()
        finally:
            conn.close()
        logger.info("Account deletion requested for user_id=%s", user_id)
        # Force logout
        cookie_name = session_service.get_session_cookie_name()
        resp = RedirectResponse(url="/login?msg=deletion_requested", status_code=302)
        resp.delete_cookie(cookie_name)
        return resp

    @router.post("/settings/cancel-deletion", response_class=RedirectResponse)
    def portal_cancel_deletion(
        request: Request,
        issuer: dict = Depends(get_portal_issuer),
        csrf_token: str = Form(""),
    ):
        """Cancel a pending account deletion request."""
        if not csrf_service.verify_csrf_token(csrf_token):
            raise HTTPException(status_code=403, detail="Token CSRF inválido o expirado")
        user_id = getattr(request.state, "user_id", None) or 0
        if not user_id:
            raise HTTPException(status_code=401, detail="Sesión inválida")
        conn = db()
        try:
            conn.execute(
                "UPDATE account_deletion_requests SET status = 'rejected', reviewed_at = datetime('now'), "
                "reviewer_notes = 'Cancelled by user' WHERE user_id = ? AND status = 'pending'",
                (user_id,),
            )
            conn.commit()
        finally:
            conn.close()
        logger.info("Account deletion cancelled by user_id=%s", user_id)
        return RedirectResponse(
            url="/portal/settings?success=Solicitud+de+eliminación+cancelada",
            status_code=302,
        )
