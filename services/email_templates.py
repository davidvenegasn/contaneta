"""Email template rendering service.

Provides stateless functions to render transactional HTML email templates
using Jinja2. All templates extend a responsive base layout with ContaNeta
branding, dark mode support, and email client compatibility.
"""

import logging
import os
from datetime import datetime, timezone
from typing import Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape

logger = logging.getLogger(__name__)

# Resolve templates directory relative to project root
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TEMPLATES_DIR = os.path.join(_BASE_DIR, "templates")

# Standalone Jinja2 environment for email rendering (separate from FastAPI's).
# Autoescape enabled to prevent XSS in rendered HTML emails.
_env = Environment(
    loader=FileSystemLoader(_TEMPLATES_DIR),
    autoescape=select_autoescape(["html"]),
)


def _current_year() -> str:
    """Return current year as string for copyright notices."""
    return str(datetime.now(timezone.utc).year)


def render_email(template_name: str, context: Optional[dict] = None) -> str:
    """Render an email template with Jinja2.

    Args:
        template_name: Template path relative to templates dir
            (e.g. 'email/welcome.html').
        context: Dict of variables to pass to the template.

    Returns:
        Rendered HTML string.

    Raises:
        jinja2.TemplateNotFound: If the template does not exist.
    """
    ctx = dict(context) if context else {}
    ctx.setdefault("current_year", _current_year())
    template = _env.get_template(template_name)
    return template.render(**ctx)


def render_welcome_email(user_name: str, login_url: str) -> str:
    """Render the welcome email sent after user registration.

    Args:
        user_name: Display name of the new user.
        login_url: URL to the login/portal page.

    Returns:
        Rendered HTML string.
    """
    return render_email("email/welcome.html", {
        "user_name": user_name,
        "login_url": login_url,
        "preheader": "Bienvenido a ContaNeta. Tu cuenta ha sido creada.",
    })


def render_invoice_email(invoice_data: dict, portal_url: str) -> str:
    """Render the invoice sent notification email.

    Args:
        invoice_data: Dict with invoice details. Expected keys:
            folio, receptor_name, receptor_rfc, date, total.
        portal_url: URL to view the invoice in the portal.

    Returns:
        Rendered HTML string.
    """
    folio = invoice_data.get("folio", "")
    preheader = f"Factura {folio} emitida" if folio else "Nueva factura emitida"
    return render_email("email/invoice_sent.html", {
        "invoice": invoice_data,
        "portal_url": portal_url,
        "preheader": preheader,
    })


def render_quotation_email(quotation_data: dict, public_url: str) -> str:
    """Render the quotation sent notification email.

    Args:
        quotation_data: Dict with quotation details. Expected keys:
            folio, client_name, date, valid_until, total.
        public_url: Public URL to view the quotation.

    Returns:
        Rendered HTML string.
    """
    folio = quotation_data.get("folio", "")
    preheader = f"Cotizacion {folio}" if folio else "Nueva cotizacion"
    return render_email("email/quotation_sent.html", {
        "quotation": quotation_data,
        "public_url": public_url,
        "preheader": preheader,
    })


def render_password_reset_email(reset_url: str, expiry_minutes: int) -> str:
    """Render the password reset email.

    Args:
        reset_url: URL with the password reset token.
        expiry_minutes: Number of minutes until the link expires.

    Returns:
        Rendered HTML string.
    """
    return render_email("email/password_reset.html", {
        "reset_url": reset_url,
        "expiry_minutes": expiry_minutes,
        "preheader": "Solicitud para restablecer tu contrasena en ContaNeta.",
    })


def render_payment_email(payment_data: dict) -> str:
    """Render the payment received confirmation email.

    Args:
        payment_data: Dict with payment details. Expected keys:
            amount, currency, date, method, invoice_folio,
            payer_name, reference.

    Returns:
        Rendered HTML string.
    """
    amount = payment_data.get("amount", "")
    preheader = f"Pago de ${amount} recibido" if amount else "Pago recibido"
    return render_email("email/payment_received.html", {
        "payment": payment_data,
        "preheader": preheader,
    })
