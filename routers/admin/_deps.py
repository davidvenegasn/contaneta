"""Admin auth dependencies and helpers."""
import os
import secrets

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from services.auth import session, users

basic_auth = HTTPBasic(auto_error=False)


def _get_session_user_and_issuer(request: Request) -> tuple[int, int, int | None]:
    """Obtiene (user_id, issuer_id, restore_issuer_id) de la cookie. Lanza 403 si no hay sesión válida."""
    cookie_val = request.cookies.get(session.get_session_cookie_name())
    data = session.verify_session(cookie_val)
    if not data or data[0] <= 0:
        raise HTTPException(status_code=403, detail="Solo usuarios autenticados")
    user_id, issuer_id = data[0], data[1]
    restore_issuer_id = data[2] if len(data) >= 3 else None
    return user_id, issuer_id, restore_issuer_id


def _require_basic_if_configured(credentials: HTTPBasicCredentials | None) -> None:
    pw = (os.getenv("ADMIN_PASSWORD") or "").strip()
    if not pw:
        return
    if credentials is None or not secrets.compare_digest((credentials.password or ""), pw):
        raise HTTPException(
            status_code=401,
            detail="BasicAuth requerido",
            headers={"WWW-Authenticate": "Basic"},
        )


def require_admin(request: Request, credentials: HTTPBasicCredentials | None = Depends(basic_auth)) -> tuple[int, int, int | None]:
    """Dependency: exige sesión válida y rol admin. Devuelve (user_id, issuer_id, restore_issuer_id)."""
    _require_basic_if_configured(credentials)
    user_id, issuer_id, restore_issuer_id = _get_session_user_and_issuer(request)
    if not users.user_has_admin_role(user_id):
        raise HTTPException(status_code=403, detail="Solo administradores pueden usar esta acción")
    return user_id, issuer_id, restore_issuer_id


def require_admin_or_owner(request: Request, credentials: HTTPBasicCredentials | None = Depends(basic_auth)) -> tuple[int, int, int | None]:
    """Dependency: exige sesión válida y rol admin u owner. Devuelve (user_id, issuer_id, restore_issuer_id)."""
    _require_basic_if_configured(credentials)
    user_id, issuer_id, restore_issuer_id = _get_session_user_and_issuer(request)
    if not users.user_has_admin_or_owner_role(user_id):
        raise HTTPException(status_code=403, detail="Solo administradores u owners pueden acceder al panel admin")
    return user_id, issuer_id, restore_issuer_id
