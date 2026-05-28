"""Auth OAuth routes: Google and Facebook callbacks, debug-oauth."""
import logging
import os

import httpx
from fastapi import HTTPException, Query, Request
from fastapi.responses import RedirectResponse

from config import DEV_MODE, _env_path
from routers.auth._helpers import oauth_redirect_base
from services.auth import session, users

logger = logging.getLogger(__name__)


def register_oauth_routes(router, templates):
    """Register Google/Facebook OAuth callback and debug routes."""
    cookie_name = session.get_session_cookie_name()

    @router.get("/auth/google/callback", response_class=RedirectResponse)
    async def auth_google_callback(request: Request, code: str | None = Query(None), error: str | None = Query(None)):
        if error or not code:
            return RedirectResponse(url="/login?error=oauth", status_code=302)
        base = oauth_redirect_base(request)
        client_id = os.getenv("GOOGLE_CLIENT_ID", "").strip()
        client_secret = os.getenv("GOOGLE_CLIENT_SECRET", "").strip()
        if not client_id or not client_secret:
            return RedirectResponse(url="/login?error=oauth_config", status_code=302)
        async with httpx.AsyncClient() as client:
            token_res = await client.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "code": code,
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "redirect_uri": f"{base}/auth/google/callback",
                    "grant_type": "authorization_code",
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        if token_res.status_code != 200:
            logger.warning("Google token exchange failed: status=%s", token_res.status_code)
            return RedirectResponse(url="/login?error=oauth", status_code=302)
        try:
            token_data = token_res.json()
            access_token = token_data.get("access_token")
        except Exception:
            return RedirectResponse(url="/login?error=oauth", status_code=302)
        if not access_token:
            return RedirectResponse(url="/login?error=oauth", status_code=302)
        async with httpx.AsyncClient() as client:
            user_res = await client.get(
                "https://www.googleapis.com/oauth2/v2/userinfo",
                headers={"Authorization": f"Bearer {access_token}"},
            )
        if user_res.status_code != 200:
            return RedirectResponse(url="/login?error=oauth", status_code=302)
        try:
            user_info = user_res.json()
            oauth_id = user_info.get("id") or user_info.get("sub")
            email = (user_info.get("email") or "").strip().lower() or None
            name_oauth = (user_info.get("name") or "").strip()
            if not name_oauth:
                given = (user_info.get("given_name") or "").strip()
                family = (user_info.get("family_name") or "").strip()
                name_oauth = f"{given} {family}".strip() or None
            else:
                name_oauth = name_oauth or None
        except Exception:
            return RedirectResponse(url="/login?error=oauth", status_code=302)
        if not oauth_id:
            return RedirectResponse(url="/login?error=oauth", status_code=302)
        phone_oauth = None
        try:
            async with httpx.AsyncClient() as ac:
                people_res = await ac.get(
                    "https://people.googleapis.com/v1/people/me?personFields=phoneNumbers",
                    headers={"Authorization": f"Bearer {access_token}"},
                )
            if people_res.status_code == 200:
                data = people_res.json()
                for p in (data.get("phoneNumbers") or []):
                    val = (p.get("value") or "").strip()
                    if val:
                        phone_oauth = val
                        break
        except Exception:
            pass
        user = users.get_or_create_user_by_oauth("google", oauth_id, email=email, name=name_oauth, phone=phone_oauth)
        memberships = users.get_memberships_for_user(user["id"])
        if not memberships:
            resp = RedirectResponse(url="/confirmar-perfil", status_code=302)
            resp.set_cookie(
                cookie_name,
                session.sign_session(user["id"], 0),
                **session.session_cookie_params(request),
            )
            return resp
        if len(memberships) == 1:
            resp = RedirectResponse(url="/portal/home", status_code=302)
            resp.set_cookie(
                cookie_name,
                session.sign_session(user["id"], memberships[0]["issuer_id"]),
                **session.session_cookie_params(request),
            )
            return resp
        resp = RedirectResponse(url="/choose-issuer", status_code=302)
        resp.set_cookie(
            cookie_name,
            session.sign_session(user["id"], 0),
            **session.session_cookie_params(request),
        )
        return resp

    @router.get("/auth/facebook/callback", response_class=RedirectResponse)
    async def auth_facebook_callback(request: Request, code: str | None = Query(None), error: str | None = Query(None)):
        if error or not code:
            return RedirectResponse(url="/login?error=oauth", status_code=302)
        base = oauth_redirect_base(request)
        app_id = os.getenv("FACEBOOK_APP_ID", "").strip()
        app_secret = os.getenv("FACEBOOK_APP_SECRET", "").strip()
        if not app_id or not app_secret:
            return RedirectResponse(url="/login?error=oauth_config", status_code=302)
        async with httpx.AsyncClient() as client:
            token_res = await client.get(
                "https://graph.facebook.com/v18.0/oauth/access_token",
                params={
                    "client_id": app_id,
                    "client_secret": app_secret,
                    "redirect_uri": f"{base}/auth/facebook/callback",
                    "code": code,
                },
            )
        if token_res.status_code != 200:
            logger.warning("Facebook token exchange failed: status=%s", token_res.status_code)
            return RedirectResponse(url="/login?error=oauth", status_code=302)
        try:
            token_data = token_res.json()
            access_token = token_data.get("access_token")
        except Exception:
            return RedirectResponse(url="/login?error=oauth", status_code=302)
        if not access_token:
            return RedirectResponse(url="/login?error=oauth", status_code=302)
        async with httpx.AsyncClient() as client:
            user_res = await client.get(
                "https://graph.facebook.com/me",
                params={"fields": "id,email,name", "access_token": access_token},
            )
        if user_res.status_code != 200:
            return RedirectResponse(url="/login?error=oauth", status_code=302)
        try:
            user_info = user_res.json()
            oauth_id = user_info.get("id")
            email = (user_info.get("email") or "").strip().lower() or None
        except Exception:
            return RedirectResponse(url="/login?error=oauth", status_code=302)
        if not oauth_id:
            return RedirectResponse(url="/login?error=oauth", status_code=302)
        name_oauth = (user_info.get("name") or "").strip() or None
        user = users.get_or_create_user_by_oauth("facebook", oauth_id, email=email, name=name_oauth)
        memberships = users.get_memberships_for_user(user["id"])
        if not memberships:
            resp = RedirectResponse(url="/confirmar-perfil", status_code=302)
            resp.set_cookie(
                cookie_name,
                session.sign_session(user["id"], 0),
                **session.session_cookie_params(request),
            )
            return resp
        if len(memberships) == 1:
            resp = RedirectResponse(url="/portal/home", status_code=302)
            resp.set_cookie(
                cookie_name,
                session.sign_session(user["id"], memberships[0]["issuer_id"]),
                **session.session_cookie_params(request),
            )
            return resp
        resp = RedirectResponse(url="/choose-issuer", status_code=302)
        resp.set_cookie(
            cookie_name,
            session.sign_session(user["id"], 0),
            **session.session_cookie_params(request),
        )
        return resp

    @router.get("/debug-oauth")
    def debug_oauth():
        if not DEV_MODE:
            raise HTTPException(status_code=404, detail="Not found")
        cid = os.getenv("GOOGLE_CLIENT_ID", "").strip()
        return {
            "GOOGLE_CLIENT_ID_set": bool(cid),
            "GOOGLE_CLIENT_ID_len": len(cid),
            "env_file_used": _env_path,
            "env_file_exists": os.path.isfile(_env_path),
        }
