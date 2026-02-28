"""Dependencias FastAPI (get_portal_issuer)."""
import logging

from fastapi import Request, HTTPException

from config import ALLOW_DEMO_PORTAL, DEV_MODE, DEV_TOKEN
from services import issuers, session, users
from services import rate_limit as rate_limit_service

logger = logging.getLogger(__name__)


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

    if token_query:
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

    session_data = session.verify_session(cookie_val)
    if session_data is not None:
        user_id = session_data[0]
        issuer_id = session_data[1]
        restore_issuer_id = session_data[2] if len(session_data) >= 3 else None
        if issuer_id == 0:
            if is_api:
                raise HTTPException(status_code=403, detail="Completa tu perfil fiscal en onboarding.")
            raise HTTPException(status_code=401, detail="No autorizado - redirigir a /onboarding")
        issuer = issuers.get_issuer_by_id(issuer_id)
        if issuer:
            if user_id > 0:
                mem = users.get_membership(user_id, issuer_id)
                if not mem:
                    pass
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
