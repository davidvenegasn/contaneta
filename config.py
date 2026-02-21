"""Configuración desde variables de entorno. Cargar al inicio de la aplicación."""
import os
import secrets

from dotenv import load_dotenv

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
DEV_TOKEN = os.getenv("DEV_TOKEN", "demo")

FIRM_USER_EMAIL = (os.getenv("FIRM_USER_EMAIL") or "").strip() or None

_demo_issuer = os.getenv("DEMO_ISSUER_ID", "").strip()
DEMO_ISSUER_ID = int(_demo_issuer) if _demo_issuer.isdigit() else None
COOKIE_DEMO_VIEW = "portal_demo_view"

# En prod OBLIGATORIO: SESSION_SECRET definido en .env (valor fijo). Si falta, se usa aleatorio y se emite warning al arranque.
_session_secret_env = (os.getenv("SESSION_SECRET") or "").strip()
SESSION_SECRET = _session_secret_env if _session_secret_env else secrets.token_hex(32)
SESSION_SECRET_FROM_ENV = bool(_session_secret_env)
SESSION_COOKIE_NAME = "portal_session"
SESSION_TTL_DAYS = int(os.getenv("SESSION_TTL_DAYS", "7"))
# En prod: Secure=True por defecto. En local (ENV=dev): 0 para HTTP.
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "1" if IS_PROD else "0") == "1"

# Etiquetas de régimen fiscal (RESICO, AE) -> código SAT para CFDI
REGIMEN_LABEL_TO_CODE = {"RESICO": "626", "AE": "612"}

# Billing (Stripe)
STRIPE_SECRET_KEY = (os.getenv("STRIPE_SECRET_KEY") or "").strip() or None
STRIPE_WEBHOOK_SECRET = (os.getenv("STRIPE_WEBHOOK_SECRET") or "").strip() or None
STRIPE_PRICE_ID = (os.getenv("STRIPE_PRICE_ID") or "").strip() or None
SITE_URL = (os.getenv("SITE_URL") or "").strip() or None
