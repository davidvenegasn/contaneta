"""Configuración desde variables de entorno. Cargar al inicio de la aplicación."""
import logging
import os
import secrets

from dotenv import load_dotenv

_log = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_env_path = os.path.join(BASE_DIR, ".env")
load_dotenv(dotenv_path=_env_path, override=True)

STATIC_DIR = os.path.join(BASE_DIR, "static")
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")

DB_PATH = os.getenv("APP_DB_PATH") or os.path.join(BASE_DIR, "invoicing.db")
CATALOGS_DB = os.path.join(BASE_DIR, "catalogs", "catalogs.db")

# ENV/IS_PROD se resuelven primero para definir el default de DEV_MODE.
ENV = (os.getenv("ENV") or "dev").strip().lower()
IS_PROD = ENV == "prod"

# DEV_MODE: solo 1 si está explícitamente "1". Default 0 en prod (y cualquier no-dev), 1 en dev.
# Evita caer al demo por defecto en entornos no explícitamente de desarrollo.
_DEV_MODE_DEFAULT = "1" if ENV == "dev" else "0"
DEV_MODE = os.getenv("DEV_MODE", _DEV_MODE_DEFAULT) == "1"
# Solo con ALLOW_DEMO_PORTAL=1 (y DEV_MODE=1) se permite fallback a demo en rutas HTML del portal.
# Sin esto, sin cookie válida siempre se redirige a /login (HTML) o 401 (API).
ALLOW_DEMO_PORTAL = os.getenv("ALLOW_DEMO_PORTAL", "0") == "1"
# Token legacy por query string (solo compatibilidad temporal). Recomendado: 0 en prod.
ALLOW_LEGACY_TOKEN_LOGIN = os.getenv("ALLOW_LEGACY_TOKEN_LOGIN", "1" if ENV == "dev" else "0") == "1"
DEV_TOKEN = os.getenv("DEV_TOKEN", "demo")
# DEV_FIXTURES=1: en listados (GET clients/products/issued/received) devolver JSON de tests/manual_fixtures
# en lugar de consultar DB. Útil para desarrollar UI sin SAT/DB.
DEV_FIXTURES = os.getenv("DEV_FIXTURES", "0") == "1"

FIRM_USER_EMAIL = (os.getenv("FIRM_USER_EMAIL") or "").strip() or None

_demo_issuer = os.getenv("DEMO_ISSUER_ID", "").strip()
DEMO_ISSUER_ID = int(_demo_issuer) if _demo_issuer.isdigit() else None
COOKIE_DEMO_VIEW = "portal_demo_view"

# En prod OBLIGATORIO: SESSION_SECRET definido en .env. Si falta en prod, no arrancar (RuntimeError).
# En dev: si falta, se usa valor aleatorio (warning al cargar config no necesario; opcional en startup).
_session_secret_env = (os.getenv("SESSION_SECRET") or "").strip()
if ENV == "prod" and not _session_secret_env:
    raise RuntimeError(
        "SESSION_SECRET is required in production (ENV=prod). "
        "Set it in .env. Generate one: python3 -c \"import secrets; print(secrets.token_hex(32))\""
    )
SESSION_SECRET = _session_secret_env if _session_secret_env else secrets.token_hex(32)
SESSION_SECRET_FROM_ENV = bool(_session_secret_env)
if not _session_secret_env and ENV == "dev":
    _log.warning(
        "SESSION_SECRET no definido en .env; usando valor aleatorio (solo válido para esta ejecución). "
        "En producción (ENV=prod) la aplicación no arranca sin SESSION_SECRET."
    )
SESSION_COOKIE_NAME = "portal_session"
SESSION_TTL_DAYS = int(os.getenv("SESSION_TTL_DAYS", "7"))
# En prod: Secure=True por defecto. En local (ENV=dev): 0 para HTTP.
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "1" if IS_PROD else "0") == "1"

# Etiquetas de régimen fiscal (RESICO, AE) -> código SAT para CFDI
REGIMEN_LABEL_TO_CODE = {"RESICO": "626", "AE": "612"}

# Código SAT -> descripción legible del régimen fiscal
REGIMEN_CODE_DESCRIPTIONS = {
    "601": "General de Ley Personas Morales",
    "603": "Personas Morales con Fines no Lucrativos",
    "605": "Sueldos y Salarios e Ingresos Asimilados a Salarios",
    "606": "Arrendamiento",
    "607": "Régimen de Enajenación o Adquisición de Bienes",
    "608": "Demás ingresos",
    "610": "Residentes en el Extranjero sin Establecimiento Permanente en México",
    "611": "Ingresos por Dividendos (socios y accionistas)",
    "612": "Personas Físicas con Actividades Empresariales y Profesionales",
    "614": "Ingresos por intereses",
    "615": "Régimen de los ingresos por obtención de premios",
    "616": "Sin obligaciones fiscales",
    "620": "Sociedades Cooperativas de Producción que optan por diferir sus ingresos",
    "621": "Incorporación Fiscal",
    "622": "Actividades Agrícolas, Ganaderas, Silvícolas y Pesqueras",
    "623": "Opcional para Grupos de Sociedades",
    "624": "Coordinados",
    "625": "Régimen de las Actividades Empresariales con ingresos a través de Plataformas Tecnológicas",
    "626": "Régimen Simplificado de Confianza",
}

# Billing (Stripe)
STRIPE_SECRET_KEY = (os.getenv("STRIPE_SECRET_KEY") or "").strip() or None
STRIPE_WEBHOOK_SECRET = (os.getenv("STRIPE_WEBHOOK_SECRET") or "").strip() or None
STRIPE_PRICE_ID = (os.getenv("STRIPE_PRICE_ID") or "").strip() or None
SITE_URL = (os.getenv("SITE_URL") or "").strip() or None

# Facturapi webhook signing secret (HMAC-SHA256 over raw body).
# Generate in Facturapi dashboard → Configuración → Webhooks → endpoint.
FACTURAPI_WEBHOOK_SECRET = (os.getenv("FACTURAPI_WEBHOOK_SECRET") or "").strip() or ""

# Portal shell V2: rail + drawer (Mindtrip-style, delgado a la izquierda solo iconos). 0 = sidebar clásico; 1 = rail + drawer.
PORTAL_SHELL_V2 = os.getenv("PORTAL_SHELL_V2", "0") == "1"

# AT_REST_MASTER_KEY: required in prod for independent encryption key
AT_REST_MASTER_KEY_SET = bool((os.getenv("AT_REST_MASTER_KEY") or "").strip())
if IS_PROD and not AT_REST_MASTER_KEY_SET:
    raise RuntimeError(
        "AT_REST_MASTER_KEY is required in production (ENV=prod). "
        "Without it, encryption keys are derived from SESSION_SECRET (insecure coupling). "
        "Generate one: python3 -c \"import secrets; print(secrets.token_hex(32))\""
    )

# Trusted proxies: only trust X-Forwarded-For when the request comes from one of these.
# Comma-separated list of IPs or CIDR blocks. Default covers localhost and common private ranges.
_trusted_proxies_raw = (os.getenv("TRUSTED_PROXIES") or "127.0.0.1,::1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16").strip()
TRUSTED_PROXIES: list[str] = [s.strip() for s in _trusted_proxies_raw.split(",") if s.strip()]

# En prod con Stripe: SITE_URL recomendado para redirects de checkout y webhooks
if IS_PROD and STRIPE_SECRET_KEY and not SITE_URL:
    _log.critical(
        "SITE_URL no está definido en producción con Stripe activo. "
        "Configura SITE_URL en .env (ej. https://tudominio.com) para redirects de checkout y correos."
    )
