import json
import logging
import os
import uuid
import sqlite3
import subprocess
from contextvars import ContextVar
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")

from migrations_runner import apply_migrations
from fastapi import FastAPI, Request, Query, Depends
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.exceptions import RequestValidationError
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from config import (
    STATIC_DIR,
    TEMPLATES_DIR,
    DB_PATH,
    SESSION_COOKIE_NAME,
    SITE_URL,
    DEV_MODE,
    DEV_TOKEN,
    IS_PROD,
    BASE_DIR,
    SESSION_SECRET_FROM_ENV,
)
from services import issuers, session
from services.errors import AppError
from routers.deps import get_portal_issuer
from routers.auth import get_auth_router
from routers.api import router as api_router
from routers.public import get_public_router
from routers.portal import get_portal_router
from routers.invoicing import get_invoicing_router
from routers.admin import get_admin_router
from routers.billing import router as billing_router

# Optional Sentry integration
_sentry_dsn = os.environ.get("SENTRY_DSN", "").strip()
if _sentry_dsn:
    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.starlette import StarletteIntegration
        sentry_sdk.init(
            dsn=_sentry_dsn,
            environment=os.environ.get("ENV", "dev"),
            traces_sample_rate=float(os.environ.get("SENTRY_TRACES_RATE", "0.1")),
            integrations=[StarletteIntegration(), FastApiIntegration()],
            send_default_pii=False,
        )
        logging.getLogger(__name__).info("Sentry initialized (env=%s)", os.environ.get("ENV", "dev"))
    except ImportError:
        logging.getLogger(__name__).warning("SENTRY_DSN set but sentry-sdk not installed. pip install sentry-sdk[fastapi]")

app = FastAPI()
if os.path.isdir(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATES_DIR)
# Jinja2 no expone getattr, min, max por defecto; los añadimos para templates que los usen
templates.env.globals["getattr"] = getattr
templates.env.globals["min"] = min
templates.env.globals["max"] = max
templates.env.globals["site_url"] = SITE_URL or ""


def _jinja_tojson(value):
    """Filtro tojson para templates (partials/bank_upload y otros)."""
    return json.dumps(value, ensure_ascii=False)


templates.env.filters["tojson"] = _jinja_tojson


def _html_404() -> str:
    return """<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>No encontrado — ContaNeta</title>
  <style>
    body { font-family: system-ui, -apple-system, sans-serif; margin: 0; padding: 2rem; background: #f1f5f9; min-height: 100vh; display: flex; align-items: center; justify-content: center; }
    .card { max-width: 420px; width: 100%; background: #fff; padding: 28px; border-radius: 16px; box-shadow: 0 4px 6px -1px rgba(0,0,0,.08), 0 2px 4px -2px rgba(0,0,0,.06); }
    h1 { margin: 0 0 8px; font-size: 1.35rem; font-weight: 600; color: #1e293b; }
    .code { font-size: 13px; color: #94a3b8; margin-bottom: 16px; }
    p { margin: 0 0 20px; color: #64748b; line-height: 1.5; }
    a { display: inline-block; color: #0ea5e9; text-decoration: none; font-weight: 500; }
    a:hover { text-decoration: underline; }
  </style>
</head>
<body>
  <div class="card">
    <h1>Página no encontrada</h1>
    <p class="code">404</p>
    <p>La ruta que buscas no existe o ha sido movida.</p>
    <p><a href="/">Ir al inicio</a></p>
  </div>
</body>
</html>"""


def _html_error(status: int, detail: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Error — ContaNeta</title>
  <style>
    body {{ font-family: system-ui, -apple-system, sans-serif; margin: 0; padding: 2rem; background: #fef2f2; min-height: 100vh; display: flex; align-items: center; justify-content: center; }}
    .card {{ max-width: 420px; width: 100%; background: #fff; padding: 28px; border-radius: 16px; box-shadow: 0 4px 6px -1px rgba(0,0,0,.08); border-left: 4px solid #dc2626; }}
    h1 {{ margin: 0 0 8px; font-size: 1.35rem; font-weight: 600; color: #b91c1c; }}
    .code {{ font-size: 13px; color: #94a3b8; margin-bottom: 16px; }}
    p {{ margin: 0 0 20px; color: #64748b; line-height: 1.5; }}
    a {{ display: inline-block; color: #0ea5e9; text-decoration: none; font-weight: 500; }}
    a:hover {{ text-decoration: underline; }}
  </style>
</head>
<body>
  <div class="card">
    <h1>Error en el servidor</h1>
    <p class="code">{status}</p>
    <p>{detail}</p>
    <p><a href="/">Ir al inicio</a></p>
  </div>
</body>
</html>"""


def _api_error_code(status_code: int) -> str:
    """Mapeo de HTTP status a código de error uniforme para la API."""
    if status_code == 400:
        return "BAD_REQUEST"
    if status_code in (401, 403):
        return "UNAUTHORIZED" if status_code == 401 else "FORBIDDEN"
    if status_code == 404:
        return "NOT_FOUND"
    if status_code >= 500:
        return "INTERNAL_ERROR"
    return "ERROR"


def _api_error_body(status_code: int, detail) -> dict:
    """Cuerpo de respuesta de error uniforme: {ok: false, error: {code, message}, detail, meta.request_id}."""
    msg = detail
    if isinstance(detail, list):
        msg = "; ".join(str(x) for x in detail) if detail else "Error de validación"
    elif not isinstance(msg, str):
        msg = str(msg) if msg is not None else "Error"
    rid = request_id_ctx.get()
    return {
        "ok": False,
        "error": {"code": _api_error_code(status_code), "message": msg},
        "detail": msg,
        "meta": {"request_id": rid},
    }

def _api_app_error_body(exc: AppError) -> dict:
    rid = request_id_ctx.get()
    body = {
        "ok": False,
        "error": {"code": exc.code, "message": exc.public_message},
        "meta": {"request_id": rid},
    }
    if exc.meta:
        # mezclar meta extra sin pisar request_id
        m = dict(exc.meta)
        m.setdefault("request_id", rid)
        body["meta"] = m
    return body


@app.exception_handler(404)
async def not_found_handler(request: Request, _exc):
    accept = (request.headers.get("accept") or "").lower()
    if "text/html" in accept:
        return HTMLResponse(_html_404(), status_code=404)
    from fastapi.responses import JSONResponse
    path = (request.url.path or "")
    if path.startswith("/api/"):
        return JSONResponse(_api_error_body(404, "Not Found"), status_code=404)
    return JSONResponse({"detail": "Not Found"}, status_code=404)


@app.exception_handler(500)
async def server_error_handler(request: Request, exc: Exception):
    """Errores no controlados: log completo, respuesta genérica al cliente (sin stack ni rutas internas)."""
    logging.exception("Unhandled error: %s", exc)
    try:
        from services import error_events as error_events_service

        error_events_service.log_error_event(
            request=request,
            status=500,
            message_public="Error interno del servidor.",
            message_internal=f"Unhandled {type(exc).__name__}: {str(exc)}",
            exc=exc,
        )
    except Exception:
        pass
    accept = (request.headers.get("accept") or "").lower()
    if "text/html" in accept:
        rid = getattr(request.state, "request_id", request_id_ctx.get())
        return HTMLResponse(_html_error(500, f"Ha ocurrido un error en el servidor. Intenta de nuevo. (ID: {rid})"), status_code=500)
    from fastapi.responses import JSONResponse
    path = (request.url.path or "")
    if path.startswith("/api/"):
        return JSONResponse(_api_error_body(500, "Error interno del servidor. Intenta de nuevo."), status_code=500)
    return JSONResponse({"detail": "Internal Server Error"}, status_code=500)

@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError):
    """
    Errores controlados del dominio.
    - HTML: página bonita con ID
    - JSON (/api): contrato consistente con code + request_id
    """
    # Log interno (sin filtrar) para debug. No exponer internal_message al usuario.
    if exc.status_code >= 500:
        logging.error("AppError %s (%s): %s", exc.code, exc.status_code, exc.internal_message or exc.public_message, exc_info=True)
        try:
            from services import error_events as error_events_service

            error_events_service.log_error_event(
                request=request,
                status=exc.status_code,
                message_public=exc.public_message,
                message_internal=f"{exc.code}: {exc.internal_message or exc.public_message}",
                exc=exc,
            )
        except Exception:
            pass
    else:
        logging.info("AppError %s (%s): %s", exc.code, exc.status_code, exc.internal_message or exc.public_message)

    accept = (request.headers.get("accept") or "").lower()
    path = (request.url.path or "")
    is_api = path.startswith("/api/") or path.startswith("/download/")
    if is_api:
        from fastapi.responses import JSONResponse
        return JSONResponse(_api_app_error_body(exc), status_code=exc.status_code)
    if "text/html" in accept:
        rid = getattr(request.state, "request_id", request_id_ctx.get())
        return HTMLResponse(_html_http_error(exc.status_code, f"{exc.public_message} (ID: {rid})"), status_code=exc.status_code)
    from fastapi.responses import JSONResponse
    return JSONResponse({"detail": exc.public_message}, status_code=exc.status_code)

@app.exception_handler(sqlite3.Error)
async def sqlite_error_handler(request: Request, exc: sqlite3.Error):
    # DB failures son 500 (no 400)
    logging.exception("SQLite error: %s", exc)
    try:
        from services import error_events as error_events_service

        error_events_service.log_error_event(
            request=request,
            status=500,
            message_public="Error de base de datos.",
            message_internal=f"DB_ERROR: {str(exc)}",
            exc=exc,
        )
    except Exception:
        pass
    accept = (request.headers.get("accept") or "").lower()
    path = (request.url.path or "")
    is_api = path.startswith("/api/") or path.startswith("/download/")
    if is_api:
        from fastapi.responses import JSONResponse
        return JSONResponse(
            _api_app_error_body(AppError(code="DB_ERROR", public_message="No pudimos completar la acción. Intenta de nuevo.", internal_message=str(exc), status_code=500)),
            status_code=500,
        )
    if "text/html" in accept:
        rid = getattr(request.state, "request_id", request_id_ctx.get())
        return HTMLResponse(_html_error(500, f"No pudimos completar la acción. Intenta de nuevo. (ID: {rid})"), status_code=500)
    from fastapi.responses import JSONResponse
    return JSONResponse({"detail": "Internal Server Error"}, status_code=500)

@app.exception_handler(subprocess.CalledProcessError)
async def subprocess_error_handler(request: Request, exc: subprocess.CalledProcessError):
    logging.exception("Subprocess error: %s", exc)
    try:
        from services import error_events as error_events_service

        error_events_service.log_error_event(
            request=request,
            status=500,
            message_public="Error interno del servidor.",
            message_internal=f"SUBPROCESS_ERROR: returncode={getattr(exc, 'returncode', None)}",
            exc=exc,
        )
    except Exception:
        pass
    path = (request.url.path or "")
    is_api = path.startswith("/api/") or path.startswith("/download/")
    if is_api:
        from fastapi.responses import JSONResponse
        return JSONResponse(
            _api_app_error_body(AppError(code="SUBPROCESS_ERROR", public_message="No pudimos completar la acción. Intenta de nuevo.", internal_message=str(exc), status_code=500)),
            status_code=500,
        )
    rid = getattr(request.state, "request_id", request_id_ctx.get())
    return HTMLResponse(_html_error(500, f"No pudimos completar la acción. Intenta de nuevo. (ID: {rid})"), status_code=500)


def _html_http_error(status_code: int, detail) -> str:
    """Página de error HTML coherente para el portal: título según código y CTA (Volver al inicio / Reintentar)."""
    detail_str = detail
    if isinstance(detail, list):
        detail_str = "; ".join(str(x) for x in detail) if detail else "Ha ocurrido un error."
    elif not isinstance(detail_str, str):
        detail_str = str(detail_str) if detail_str is not None else "Ha ocurrido un error."
    titles = {
        400: "Solicitud incorrecta",
        401: "Sesión inválida",
        403: "Sin permiso",
        404: "No encontrado",
        429: "Demasiados intentos",
        500: "Error en el servidor",
        503: "Servicio no disponible",
    }
    title = titles.get(status_code, "Error")
    return f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>{title} — ContaNeta</title>
  <style>
    body {{ font-family: system-ui, -apple-system, sans-serif; margin: 0; padding: 2rem; background: #f1f5f9; min-height: 100vh; display: flex; align-items: center; justify-content: center; }}
    .card {{ max-width: 420px; width: 100%; background: #fff; padding: 28px; border-radius: 16px; box-shadow: 0 4px 6px -1px rgba(0,0,0,.08); border-left: 4px solid #dc2626; }}
    h1 {{ margin: 0 0 8px; font-size: 1.35rem; font-weight: 600; color: #1e293b; }}
    .code {{ font-size: 13px; color: #94a3b8; margin-bottom: 16px; }}
    p {{ margin: 0 0 20px; color: #64748b; line-height: 1.5; }}
    .cta {{ display: flex; gap: 12px; flex-wrap: wrap; margin-top: 24px; }}
    a {{ display: inline-block; padding: 10px 16px; border-radius: 8px; color: #0ea5e9; text-decoration: none; font-weight: 500; border: 1px solid #e2e8f0; background: #fff; }}
    a:hover {{ background: #f8fafc; text-decoration: none; }}
    a.primary {{ background: #0d9488; color: #fff; border-color: #0d9488; }}
    a.primary:hover {{ background: #0f766e; }}
  </style>
</head>
<body>
  <div class="card">
    <h1>{title}</h1>
    <p class="code">{status_code}</p>
    <p>{detail_str}</p>
    <div class="cta">
      <a href="/" class="primary">Ir al inicio</a>
      <a href="javascript:location.reload()">Reintentar</a>
    </div>
  </div>
</body>
</html>"""


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """Para 401/403 en peticiones HTML del portal, redirigir al login. Resto: HTML con CTA o JSON según Accept."""
    path = request.url.path or ""
    is_api = path.startswith("/api/") or path.startswith("/download/")
    accept = (request.headers.get("accept") or "").lower()
    if exc.status_code in (401, 403) and "text/html" in accept and not is_api:
        return RedirectResponse(url="/login", status_code=302)
    from fastapi.responses import JSONResponse
    if is_api:
        return JSONResponse(_api_error_body(exc.status_code, exc.detail), status_code=exc.status_code)
    if "text/html" in accept:
        return HTMLResponse(_html_http_error(exc.status_code, exc.detail), status_code=exc.status_code)
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)


@app.exception_handler(RequestValidationError)
async def request_validation_handler(request: Request, exc: RequestValidationError):
    """
    Pydantic/FastAPI validation error:
    - Tratamos como 400 (error del usuario), no 422, para mantener criterio del producto.
    - Para /api/* devolvemos contrato uniforme {ok:false,error:{code,message},meta:{request_id}}.
    """
    # Construir un mensaje humano (sin dump gigante)
    msg = "Error de validación"
    try:
        errs = exc.errors() or []
        parts = []
        for e in errs[:6]:
            loc = ".".join([str(x) for x in (e.get("loc") or []) if x not in ("body", "query", "path")])
            t = (e.get("msg") or "").strip()
            if loc and t:
                parts.append(f"{loc}: {t}")
            elif t:
                parts.append(t)
        if parts:
            msg = "; ".join(parts)
    except Exception:
        pass

    path = (request.url.path or "")
    accept = (request.headers.get("accept") or "").lower()
    is_api = path.startswith("/api/") or path.startswith("/download/")
    if is_api:
        from fastapi.responses import JSONResponse
        return JSONResponse(_api_error_body(400, msg), status_code=400)
    if "text/html" in accept:
        rid = getattr(request.state, "request_id", request_id_ctx.get())
        return HTMLResponse(_html_http_error(400, f"{msg} (ID: {rid})"), status_code=400)
    from fastapi.responses import JSONResponse
    return JSONResponse({"detail": msg}, status_code=400)


def _configure_logging() -> None:
    log_format = os.getenv("LOG_FORMAT", "%(message)s")
    if os.getenv("LOG_REQUEST_ID", "1") == "1":
        log_format = "[%(request_id)s] " + log_format
    logging.basicConfig(level=logging.INFO, format=log_format)
    # Añadir request_id al log record desde context var (por defecto '-' si no hay request)
    old_factory = logging.getLogRecordFactory()
    def record_factory(*args, **kwargs):
        record = old_factory(*args, **kwargs)
        record.request_id = request_id_ctx.get()
        return record
    logging.setLogRecordFactory(record_factory)
    log_file = os.getenv("LOG_FILE", "").strip()
    if log_file:
        root = logging.getLogger()
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setLevel(logging.INFO)
        fh.setFormatter(logging.Formatter(log_format))
        root.addHandler(fh)


def _startup_config_check() -> None:
    """
    Checklist de configuración al arranque. En prod falla si falta algo crítico.
    Imprime cada ítem en log para que deploy vea el estado sin sorpresas.
    """
    import shutil

    log = logging.getLogger(__name__)
    critical_failures = []

    # SESSION_SECRET: en prod ya validado en config (no se llega aquí sin él). Solo reportar.
    if SESSION_SECRET_FROM_ENV:
        log.info("[startup] SESSION_SECRET: ok (from env)")
    else:
        if IS_PROD:
            critical_failures.append("SESSION_SECRET (no debería llegar aquí; revisar config)")
        else:
            log.warning("[startup] SESSION_SECRET: using random (set in .env for stable sessions)")

    # SITE_URL: en prod necesario para redirects, billing, OAuth.
    if SITE_URL and str(SITE_URL).strip().startswith("http"):
        log.info("[startup] SITE_URL: ok")
    else:
        if IS_PROD:
            critical_failures.append("SITE_URL must be set and start with http(s) in production")
        else:
            log.warning("[startup] SITE_URL: not set (redirects may use request host)")

    # PHP: requerido solo si SAT está habilitado (existe sat_sync/check_fiel.php).
    sat_check_fiel = os.path.join(BASE_DIR, "sat_sync", "check_fiel.php")
    sat_enabled = os.path.isfile(sat_check_fiel)
    php_ok = bool(shutil.which("php"))
    if sat_enabled:
        if php_ok:
            log.info("[startup] PHP (SAT): ok")
        else:
            if IS_PROD:
                critical_failures.append("PHP not found; required for SAT/FIEL (install php-cli)")
            else:
                log.warning("[startup] PHP (SAT): not found (FIEL validation will fail)")
    else:
        log.info("[startup] PHP (SAT): skipped (no sat_sync script)")

    # Storage: debe existir y ser escribible (backups, uploads, XML).
    storage_dir = os.path.join(BASE_DIR, "storage")
    backup_dir = os.path.join(BASE_DIR, "backup")
    storage_exists = os.path.isdir(storage_dir)
    storage_writable = False
    try:
        os.makedirs(backup_dir, exist_ok=True)
        test_file = os.path.join(backup_dir, ".startup_write_test")
        with open(test_file, "w") as f:
            f.write("1")
        os.remove(test_file)
        storage_writable = True
    except Exception:
        pass
    if storage_exists and storage_writable:
        log.info("[startup] storage: ok (exists and writable)")
    else:
        if IS_PROD:
            critical_failures.append("storage directory must exist and be writable (storage/ and backup/)")
        else:
            log.warning("[startup] storage: missing or not writable")

    if critical_failures:
        msg = "Startup config check failed (ENV=prod): " + "; ".join(critical_failures)
        log.critical(msg)
        raise RuntimeError(msg)


@app.on_event("startup")
def _startup() -> None:
    _configure_logging()
    try:
        apply_migrations(DB_PATH)
    except Exception as e:
        logging.exception("Migrations failed: %s", e)
        raise
    _startup_config_check()


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or str(uuid.uuid4())[:12]
    request.state.request_id = request_id
    token = request_id_ctx.set(request_id)
    start_ms = None
    try:
        start_ms = int(__import__("time").time() * 1000)
    except Exception:
        start_ms = None
    try:
        response = await call_next(request)
        if os.getenv("LOG_REQUEST_ID", "1") == "1":
            response.headers["x-request-id"] = request_id
        if os.getenv("LOG_REQUESTS", "1") == "1":
            try:
                dur_ms = (int(__import__("time").time() * 1000) - start_ms) if start_ms is not None else None
                logging.getLogger("http").info(
                    "%s %s -> %s%s",
                    request.method,
                    request.url.path,
                    getattr(response, "status_code", "?"),
                    (" (%sms)" % dur_ms) if dur_ms is not None else "",
                )
            except Exception:
                pass
        return response
    finally:
        request_id_ctx.reset(token)


@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    """Cabeceras de seguridad: CSP básico, frame-ancestors, nosniff, referrer-policy, permissions-policy."""
    response = await call_next(request)
    if "X-Content-Type-Options" not in response.headers:
        response.headers["X-Content-Type-Options"] = "nosniff"
    if "X-Frame-Options" not in response.headers:
        response.headers["X-Frame-Options"] = "DENY"
    if "Referrer-Policy" not in response.headers:
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    if "Permissions-Policy" not in response.headers:
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=(), payment=(), usb=(), serial=()"
    if "Content-Security-Policy" not in response.headers:
        # CSP básico; frame-ancestors 'none' evita que la app se embeba en iframes
        csp = "default-src 'self'; frame-ancestors 'none'; script-src 'self' 'unsafe-inline' https://js.stripe.com; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; frame-src 'self' https://js.stripe.com https://hooks.stripe.com; img-src 'self' data:; connect-src 'self' https://api.stripe.com;"
        response.headers["Content-Security-Policy"] = csp
    return response


@app.middleware("http")
async def redirect_token_middleware(request: Request, call_next):
    token_query = request.query_params.get("token", "").strip()
    is_api = request.url.path.startswith("/api/") or request.url.path.startswith("/download/")
    is_public = request.url.path.startswith("/q/") or request.url.path.startswith("/public/")
    is_portal_html = request.url.path.startswith("/portal/") and not is_api and not is_public

    if token_query and is_portal_html:
        # Rate limit token login: max 5 attempts per IP per 60s
        from services.rate_limit import is_rate_limited, get_client_ip
        if is_rate_limited(request, "token_login", window_seconds=60, max_attempts=5):
            client_ip = get_client_ip(request)
            logging.getLogger(__name__).warning(
                "token_login rate limited: ip=%s path=%s", client_ip, request.url.path
            )
            return Response("Too Many Requests", status_code=429)
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
            logging.getLogger(__name__).info(
                "token_login failed: ip=%s path=%s", get_client_ip(request), request.url.path
            )

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


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    """Evita 404 cuando el navegador pide favicon.ico."""
    return Response(status_code=204)


def _sitemap_xml(base_url: str) -> str:
    """Genera sitemap XML simple (sin libs). base_url sin barra final."""
    if not base_url:
        base_url = "https://example.com"
    base_url = base_url.rstrip("/")
    paths = ["/", "/login", "/signup", "/pricing", "/comparar", "/demo", "/seguridad", "/terms", "/privacy"]
    out = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for path in paths:
        out.append(f"  <url><loc>{base_url}{path}</loc><changefreq>weekly</changefreq></url>")
    out.append("</urlset>")
    return "\n".join(out)


@app.get("/sitemap.xml", include_in_schema=False)
def sitemap(request: Request):
    """Sitemap para SEO. Usa SITE_URL si está definido, si no la URL de la petición."""
    base = SITE_URL or str(request.base_url).rstrip("/")
    xml = _sitemap_xml(base)
    return Response(content=xml, media_type="application/xml")


@app.get("/robots.txt", include_in_schema=False)
def robots_txt(request: Request):
    """robots.txt que referencia sitemap. Usa SITE_URL para la URL del sitemap si está definido."""
    base = SITE_URL or str(request.base_url).rstrip("/")
    body = "User-agent: *\nAllow: /\nDisallow: /portal/\nDisallow: /admin/\n"
    if base and base.startswith("http"):
        body += f"Sitemap: {base}/sitemap.xml\n"
    return Response(content=body, media_type="text/plain")


def _health_checks():
    """Devuelve dict con ok, db_readable, migrations_applied, storage_exists, storage_writable
    y campos para Support Snapshot (diagnóstico sin secretos)."""
    import os

    from config import BASE_DIR, ENV, DEV_MODE
    from database import db, db_rows

    out = {
        "ok": True,
        "db_readable": False,
        "migrations_applied": False,
        "storage_exists": False,
        "storage_writable": False,
    }
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
    storage_dir = os.path.join(BASE_DIR, "storage")
    out["storage_exists"] = os.path.isdir(storage_dir)
    try:
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

    # Support Snapshot: diagnóstico rápido sin exponer secretos ni rutas completas en prod
    out["support"] = _support_snapshot(out, ENV, DEV_MODE)
    return out


def _support_snapshot(health, env, dev_mode):
    """Indicadores para panel de soporte: sin secretos, sin último error."""
    import os
    import shutil
    from datetime import datetime, timezone

    from config import DB_PATH

    versions = health.get("migrations_versions") or []
    latest = versions[-1] if versions else None
    # En prod solo nombre del archivo; en dev se puede mostrar nombre también por seguridad
    db_path_display = os.path.basename(DB_PATH)

    php_available = bool(shutil.which("php"))
    try:
        import reportlab  # noqa: F401
        reportlab_available = True
    except ImportError:
        reportlab_available = False
    try:
        import pdfplumber  # noqa: F401
        pdfplumber_available = True
    except ImportError:
        pdfplumber_available = False

    return {
        "db_path": db_path_display,
        "migration_version": latest,
        "storage_exists": health.get("storage_exists", False),
        "storage_writable": health.get("storage_writable", False),
        "php_available": php_available,
        "reportlab_available": reportlab_available,
        "pdfplumber_available": pdfplumber_available,
        "env": env,
        "dev_mode": dev_mode,
        "server_time": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


@app.get("/health")
def health():
    """Health check para monitoreo. No requiere auth. Incluye DB, migraciones y storage. No exponer secretos ni rutas internas."""
    checks = _health_checks()
    status = "ok" if checks["db_readable"] else "degraded"
    versions = checks.get("migrations_versions") or []
    migration_version = versions[-1] if versions else None
    try:
        import pdfplumber  # noqa: F401
        pdfplumber_ok = True
    except ImportError:
        pdfplumber_ok = False
    return {
        "status": status,
        "db": "ok" if checks["db_readable"] else "error",
        "db_readable": checks["db_readable"],
        "migrations_applied": checks["migrations_applied"],
        "migration_version": migration_version,
        "storage_exists": checks["storage_exists"],
        "storage_writable": checks["storage_writable"],
        "pdfplumber_available": pdfplumber_ok,
    }


@app.get("/ready")
def ready():
    """Readiness: 200 solo si migraciones aplicadas (para balanceadores/K8s). 503 si no está listo. No exponer secretos."""
    checks = _health_checks()
    if checks["migrations_applied"] and checks["db_readable"] and checks.get("storage_exists") and checks.get("storage_writable"):
        versions = checks.get("migrations_versions") or []
        return {"ready": True, "migration_version": versions[-1] if versions else None}
    from fastapi.responses import JSONResponse
    reason = "unknown"
    if not checks["db_readable"]:
        reason = "db_not_readable"
    elif not checks["migrations_applied"]:
        reason = "migrations_not_applied"
    elif not checks.get("storage_exists"):
        reason = "storage_missing"
    elif not checks.get("storage_writable"):
        reason = "storage_not_writable"
    return JSONResponse(
        {"ready": False, "reason": reason},
        status_code=503,
    )


@app.get("/status", response_class=HTMLResponse)
def status_page():
    """Página HTML legible con estado y Support Snapshot (diagnóstico sin secretos)."""
    checks = _health_checks()
    db_ok = checks["db_readable"]
    mig_ok = checks["migrations_applied"]
    storage_exists = checks["storage_exists"]
    storage_ok = checks["storage_writable"]
    status = "ok" if checks["ok"] else "degraded"
    versions = checks.get("migrations_versions") or []
    sup = checks.get("support") or {}
    html = f"""<!DOCTYPE html>
<html lang="es">
<head><meta charset="utf-8"/><title>Status — ContaNeta</title>
<style>
  body {{ font-family: system-ui,sans-serif; margin: 24px; background: #f8fafc; }}
  .card {{ max-width: 480px; background: #fff; padding: 20px; border-radius: 12px; box-shadow: 0 1px 3px rgba(0,0,0,.08); margin-bottom: 16px; }}
  h1 {{ margin: 0 0 16px; font-size: 1.25rem; }}
  h2 {{ margin: 0 0 12px; font-size: 1rem; color: #475569; }}
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
    <div class="row"><span>Storage existe</span><span class="{'ok' if storage_exists else 'error'}">{'Sí' if storage_exists else 'No'}</span></div>
    <div class="row"><span>Storage escribible (backup)</span><span class="{'ok' if storage_ok else 'error'}">{'Sí' if storage_ok else 'No'}</span></div>
    <div class="versions">Versiones: {', '.join(versions) or '—'}</div>
  </div>
  <div class="card">
    <h2>Support Snapshot</h2>
    <div class="row"><span>DB (archivo)</span><span>{sup.get('db_path', '—')}</span></div>
    <div class="row"><span>Última migración</span><span>{sup.get('migration_version') or '—'}</span></div>
    <div class="row"><span>Storage existe</span><span class="{'ok' if sup.get('storage_exists') else 'error'}">{'Sí' if sup.get('storage_exists') else 'No'}</span></div>
    <div class="row"><span>Storage escribible</span><span class="{'ok' if sup.get('storage_writable') else 'error'}">{'Sí' if sup.get('storage_writable') else 'No'}</span></div>
    <div class="row"><span>PHP disponible</span><span class="{'ok' if sup.get('php_available') else 'error'}">{'Sí' if sup.get('php_available') else 'No'}</span></div>
    <div class="row"><span>reportlab</span><span class="{'ok' if sup.get('reportlab_available') else 'error'}">{'Sí' if sup.get('reportlab_available') else 'No'}</span></div>
    <div class="row"><span>pdfplumber</span><span class="{'ok' if sup.get('pdfplumber_available') else 'error'}">{'Sí' if sup.get('pdfplumber_available') else 'No'}</span></div>
    <div class="row"><span>ENV</span><span>{sup.get('env', '—')}</span></div>
    <div class="row"><span>DEV_MODE</span><span>{'Sí' if sup.get('dev_mode') else 'No'}</span></div>
    <div class="row"><span>Hora servidor (UTC)</span><span>{sup.get('server_time', '—')}</span></div>
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
app.include_router(billing_router)

logger = logging.getLogger(__name__)


# SESSION_SECRET en prod: validado en config.py (RuntimeError si falta); la app no arranca sin él.


# Backwards compatible URL (legacy: ?token= sigue funcionando vía dependency en /portal/create)
@app.get("/facturar", response_class=HTMLResponse)
def facturar(request: Request, token: str = Query("")):
    if token:
        return RedirectResponse(url=f"/login?token={token}", status_code=302)
    return RedirectResponse(url="/portal/create", status_code=302)


