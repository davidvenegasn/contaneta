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

DEV_MODE = os.getenv("DEV_MODE", "1") == "1"
DEV_TOKEN = os.getenv("DEV_TOKEN", "demo")

FIRM_USER_EMAIL = (os.getenv("FIRM_USER_EMAIL") or "").strip() or None

_demo_issuer = os.getenv("DEMO_ISSUER_ID", "").strip()
DEMO_ISSUER_ID = int(_demo_issuer) if _demo_issuer.isdigit() else None
COOKIE_DEMO_VIEW = "portal_demo_view"

SESSION_SECRET = os.getenv("SESSION_SECRET", secrets.token_hex(32))
SESSION_COOKIE_NAME = "portal_session"
SESSION_TTL_DAYS = int(os.getenv("SESSION_TTL_DAYS", "7"))
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "0") == "1"

# Etiquetas de régimen fiscal (RESICO, AE) -> código SAT para CFDI
REGIMEN_LABEL_TO_CODE = {"RESICO": "626", "AE": "612"}

# Billing (Stripe)
STRIPE_SECRET_KEY = (os.getenv("STRIPE_SECRET_KEY") or "").strip() or None
STRIPE_WEBHOOK_SECRET = (os.getenv("STRIPE_WEBHOOK_SECRET") or "").strip() or None
STRIPE_PRICE_ID = (os.getenv("STRIPE_PRICE_ID") or "").strip() or None
SITE_URL = (os.getenv("SITE_URL") or "").strip() or None
