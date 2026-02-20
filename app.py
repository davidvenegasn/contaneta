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
from routers.admin import get_admin_router

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


def _health_checks():
    """Devuelve dict con ok, db_readable, migrations_applied, storage_writable."""
    import os
    from database import db, db_rows
    out = {"ok": True, "db_readable": False, "migrations_applied": False, "storage_writable": False}
    try:
        if os.path.isfile(DB_PATH):
            conn = db()
            conn.execute("SELECT 1")
            conn.close()
            out["db_readable"] = True
            try:
                rows = db_rows("SELECT version FROM schema_migrations ORDER BY version")
                out["migrations_applied"] = True
                out["migrations_versions"] = [r["version"] for r in rows]
            except Exception:
                pass
    except Exception:
        pass
    try:
        from config import BASE_DIR
        backup_dir = os.path.join(BASE_DIR, "backup")
        os.makedirs(backup_dir, exist_ok=True)
        test_file = os.path.join(backup_dir, ".health_write_test")
        with open(test_file, "w") as f:
            f.write("1")
        os.remove(test_file)
        out["storage_writable"] = True
    except Exception:
        pass
    out["ok"] = out["db_readable"] and out["migrations_applied"]
    return out


@app.get("/health")
def health():
    """Health check para monitoreo y balanceadores. No requiere auth. Revisa DB accesible y versión de migración aplicada."""
    checks = _health_checks()
    status = "ok" if checks["ok"] else "degraded"
    versions = checks.get("migrations_versions") or []
    migration_version = versions[-1] if versions else None
    return {
        "status": status,
        "db": "ok" if checks["db_readable"] else "error",
        "db_readable": checks["db_readable"],
        "migrations_applied": checks["migrations_applied"],
        "migration_version": migration_version,
        "storage_writable": checks["storage_writable"],
    }


@app.get("/status", response_class=HTMLResponse)
def status_page():
    """Página HTML legible con el mismo contenido que /health."""
    checks = _health_checks()
    db_ok = checks["db_readable"]
    mig_ok = checks["migrations_applied"]
    storage_ok = checks["storage_writable"]
    status = "ok" if checks["ok"] else "degraded"
    versions = checks.get("migrations_versions") or []
    html = f"""<!DOCTYPE html>
<html lang="es">
<head><meta charset="utf-8"/><title>Status — ContaNeta</title>
<style>
  body {{ font-family: system-ui,sans-serif; margin: 24px; background: #f8fafc; }}
  .card {{ max-width: 480px; background: #fff; padding: 20px; border-radius: 12px; box-shadow: 0 1px 3px rgba(0,0,0,.08); }}
  h1 {{ margin: 0 0 16px; font-size: 1.25rem; }}
  .row {{ display: flex; justify-content: space-between; padding: 8px 0; border-bottom: 1px solid #e2e8f0; }}
  .ok {{ color: #15803d; }} .error {{ color: #b91c1c; }}
  .versions {{ font-size: 12px; color: #64748b; margin-top: 8px; }}
</style>
</head>
<body>
  <div class="card">
    <h1>Estado del sistema</h1>
    <div class="row"><span>Estado</span><span class="{'ok' if status == 'ok' else 'error'}">{status}</span></div>
    <div class="row"><span>DB legible</span><span class="{'ok' if db_ok else 'error'}">{'Sí' if db_ok else 'No'}</span></div>
    <div class="row"><span>Migraciones aplicadas</span><span class="{'ok' if mig_ok else 'error'}">{'Sí' if mig_ok else 'No'}</span></div>
    <div class="row"><span>Storage escribible</span><span class="{'ok' if storage_ok else 'error'}">{'Sí' if storage_ok else 'No'}</span></div>
    <div class="versions">Versiones: {', '.join(versions) or '—'}</div>
  </div>
</body>
</html>"""
    return HTMLResponse(html)


app.include_router(get_auth_router(templates))
app.include_router(api_router)
app.include_router(get_public_router(templates))
app.include_router(get_portal_router(templates))
app.include_router(get_invoicing_router(templates))
app.include_router(get_admin_router(templates))


# Backwards compatible URL (legacy: ?token= sigue funcionando vía dependency en /portal/create)
@app.get("/facturar", response_class=HTMLResponse)
def facturar(request: Request, token: str = Query("")):
    if token:
        return RedirectResponse(url=f"/login?token={token}", status_code=302)
    return RedirectResponse(url="/portal/create", status_code=302)


