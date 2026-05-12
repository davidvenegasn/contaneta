"""Dependencias FastAPI (get_portal_issuer)."""
import logging

from fastapi import HTTPException, Request

from config import ALLOW_DEMO_PORTAL, ALLOW_LEGACY_TOKEN_LOGIN, DEV_MODE, DEV_TOKEN, SESSION_TTL_DAYS
from database import db, db_rows, has_column
from services import issuers
from services.auth import rate_limit as rate_limit_service
from services.auth import session, users

logger = logging.getLogger(__name__)


def _session_invalidated_by_password_change(user_id: int, session_expiry: int) -> bool:
    """Check if the session was created before the user's last password change."""
    try:
        conn = db()
        if not has_column(conn, "users", "password_changed_at"):
            conn.close()
            return False
        conn.close()
        rows = db_rows(
            "SELECT password_changed_at FROM users WHERE id = ? LIMIT 1",
            (user_id,),
        )
        if not rows or not rows[0].get("password_changed_at"):
            return False
        from datetime import datetime
        pw_changed = datetime.strptime(rows[0]["password_changed_at"], "%Y-%m-%d %H:%M:%S")
        session_created = session_expiry - SESSION_TTL_DAYS * 86400
        session_created_dt = datetime.utcfromtimestamp(session_created)
        return session_created_dt < pw_changed
    except Exception:
        return False


def get_portal_issuer(request: Request) -> dict:
    """
    Autentica por cookie (user_id+issuer_id o legacy issuer_id) o por ?token= (legacy).
    Sin cookie válida: HTML → redirect /login; API → 401.
    Demo issuer solo si DEV_MODE=1 y ALLOW_DEMO_PORTAL=1 (y no es API).
    """
    cookie_name = session.get_session_cookie_name()
    cookie_demo = session.get_cookie_demo_view()
    token_query = request.query_params.get("token", "").strip()
    cookie_val = request.cookies.get(cookie_name)
    is_api = request.url.path.startswith("/api/") or request.url.path.startswith("/download/")

    if token_query and ALLOW_LEGACY_TOKEN_LOGIN:
        # Mitigar brute force sobre tokens legacy (por IP).
        if rate_limit_service.is_rate_limited(request, "token", window_seconds=60.0, max_attempts=20):
            if is_api:
                raise HTTPException(status_code=429, detail="Demasiados intentos. Espera un minuto.")
            raise HTTPException(status_code=401, detail="No autorizado - redirigir a /login")
        try:
            issuer = issuers.get_issuer_by_token(token_query)
        except ValueError:
            pass
        else:
            request.state.issuer_id = issuer["id"]
            request.state.issuer = issuer
            request.state.user_id = 0
            request.state.is_impersonating = False
            request.state.impersonation_restore_issuer_id = None
            return issuer

    session_data = session.verify_session(cookie_val, include_expiry=True)
    if session_data is not None:
        user_id = session_data[0]
        issuer_id = session_data[1]
        restore_issuer_id = session_data[2] if len(session_data) >= 3 else None
        session_expiry = session_data[3] if len(session_data) >= 4 else 0
        if issuer_id == 0:
            if is_api:
                raise HTTPException(status_code=403, detail="Completa tu perfil fiscal en onboarding.")
            raise HTTPException(status_code=401, detail="No autorizado - redirigir a /onboarding")
        issuer = issuers.get_issuer_by_id(issuer_id)
        if issuer:
            if user_id > 0:
                # Invalidate session if password was changed after session creation
                if session_expiry and _session_invalidated_by_password_change(user_id, session_expiry):
                    logger.info("Session invalidated: password changed after session creation for user_id=%s", user_id)
                    if is_api:
                        raise HTTPException(status_code=401, detail="Sesión expirada. Inicia sesión de nuevo.")
                    raise HTTPException(status_code=401, detail="No autorizado - redirigir a /login")
                mem = users.get_membership(user_id, issuer_id)
                if not mem:
                    logger.warning("Tenant isolation: user_id=%s has no membership for issuer_id=%s", user_id, issuer_id)
                    if is_api:
                        raise HTTPException(status_code=403, detail="No tienes acceso a este emisor.")
                    raise HTTPException(status_code=401, detail="No autorizado - redirigir a /login")
                else:
                    request.state.issuer_id = issuer["id"]
                    request.state.issuer = issuer
                    request.state.user_id = user_id
                    request.state.membership_role = mem.get("role")
                    request.state.is_impersonating = restore_issuer_id is not None
                    request.state.impersonation_restore_issuer_id = restore_issuer_id
                    request.state.issuer_is_placeholder = issuer.get("rfc") == "PENDIENTE"
                    if (
                        request.state.issuer_is_placeholder
                        and request.cookies.get(cookie_demo) == "1"
                    ):
                        demo = issuers.get_demo_issuer()
                        if demo:
                            request.state.is_demo_view = True
                            return demo
                    return issuer
            else:
                request.state.issuer_id = issuer["id"]
                request.state.issuer = issuer
                request.state.user_id = 0
                request.state.is_impersonating = restore_issuer_id is not None
                request.state.impersonation_restore_issuer_id = restore_issuer_id
                return issuer

    # Sin cookie válida: demo solo si explícitamente permitido (DEV_MODE + ALLOW_DEMO_PORTAL)
    if DEV_MODE and ALLOW_DEMO_PORTAL and not is_api:
        try:
            demo = issuers.get_issuer_by_token(DEV_TOKEN)
        except Exception:
            pass
        else:
            request.state.issuer_id = demo["id"]
            request.state.issuer = demo
            request.state.user_id = 0
            request.state.is_impersonating = False
            request.state.impersonation_restore_issuer_id = None
            return demo

    if is_api:
        raise HTTPException(status_code=401, detail="No autorizado")
    raise HTTPException(status_code=401, detail="No autorizado - redirigir a /login")
