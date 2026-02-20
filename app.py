import logging
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from migrations_runner import apply_migrations
from fastapi import FastAPI, Request, Query, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles

from config import (
    STATIC_DIR,
    TEMPLATES_DIR,
    DB_PATH,
    SESSION_COOKIE_NAME,
    DEV_MODE,
    DEV_TOKEN,
)
from services import issuers, session
from routers.deps import get_portal_issuer
from routers.auth import get_auth_router
from routers.api import router as api_router
from routers.public import get_public_router
from routers.portal import get_portal_router
from routers.invoicing import get_invoicing_router
from routers.admin import router as admin_router

app = FastAPI()
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATES_DIR)


@app.on_event("startup")
def _startup() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        apply_migrations(DB_PATH)
    except Exception as e:
        logging.exception("Migrations failed: %s", e)
        raise


@app.middleware("http")
async def redirect_token_middleware(request: Request, call_next):
    token_query = request.query_params.get("token", "").strip()
    is_api = request.url.path.startswith("/api/") or request.url.path.startswith("/download/")
    is_public = request.url.path.startswith("/q/") or request.url.path.startswith("/public/")
    is_portal_html = request.url.path.startswith("/portal/") and not is_api and not is_public

    if token_query and is_portal_html:
        try:
            issuer = issuers.get_issuer_by_token(token_query)
            parsed = urlparse(str(request.url))
            qs = parse_qs(parsed.query, keep_blank_values=False)
            qs.pop("token", None)
            if qs:
                new_query = urlencode(qs, doseq=True)
                new_url = urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query, parsed.fragment))
            else:
                new_url = parsed.path
            response = RedirectResponse(url=new_url, status_code=302)
            response.set_cookie(
                SESSION_COOKIE_NAME,
                session.sign_session(0, issuer["id"]),
                **session.session_cookie_params(request),
            )
            return response
        except ValueError:
            pass

    if is_portal_html and not token_query:
        cookie_val = request.cookies.get(SESSION_COOKIE_NAME)
        session_data = session.verify_session(cookie_val)
        if session_data is None and not DEV_MODE:
            return RedirectResponse(url="/login", status_code=302)
        if session_data is not None and session_data[1] == 0 and not DEV_MODE:
            return RedirectResponse(url="/confirmar-perfil", status_code=302)

    response = await call_next(request)
    return response


@app.get("/")
def root():
    return RedirectResponse(url="/portal/home")


@app.get("/health")
def health():
    """Health check para monitoreo y balanceadores. No requiere auth."""
    import os
    from database import db
    db_ok = False
    try:
        if os.path.isfile(DB_PATH):
            conn = db()
            conn.execute("SELECT 1")
            conn.close()
            db_ok = True
    except Exception:
        pass
    status = "ok" if db_ok else "degraded"
    return {"status": status, "db": "ok" if db_ok else "error"}


app.include_router(get_auth_router(templates))
app.include_router(api_router)
app.include_router(get_public_router(templates))
app.include_router(get_portal_router(templates))
app.include_router(get_invoicing_router(templates))
app.include_router(admin_router)


# Backwards compatible URL (legacy: ?token= sigue funcionando vía dependency en /portal/create)
@app.get("/facturar", response_class=HTMLResponse)
def facturar(request: Request, token: str = Query("")):
    if token:
        return RedirectResponse(url=f"/login?token={token}", status_code=302)
    return RedirectResponse(url="/portal/create", status_code=302)


