"""Envío de correos: SMTP si está configurado; en DEV sin SMTP se loguea el link/body."""
import logging
import os
import smtplib
from email.mime.text import MIMEText
from email.utils import formataddr
from typing import Optional

logger = logging.getLogger(__name__)

DEV_MODE = os.getenv("DEV_MODE", "1") == "1"
SMTP_HOST = (os.getenv("SMTP_HOST") or "").strip()
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = (os.getenv("SMTP_USER") or "").strip()
SMTP_PASSWORD = (os.getenv("SMTP_PASSWORD") or "").strip()
SMTP_FROM = (os.getenv("SMTP_FROM") or SMTP_USER or "noreply@localhost").strip()


def send_email(to: str, subject: str, body_plain: str, body_html: Optional[str] = None) -> bool:
    """
    Envía un correo. Si SMTP no está configurado y DEV_MODE=1, loguea el cuerpo (para ver links).
    Returns True si se envió o se logueó en DEV; False si falló.
    """
    to = (to or "").strip().lower()
    if not to or "@" not in to:
        return False
    if SMTP_HOST and SMTP_USER and SMTP_PASSWORD:
        try:
            msg = MIMEText(body_html or body_plain, "html" if body_html else "plain", "utf-8")
            msg["Subject"] = subject
            msg["From"] = formataddr(("ContaNeta", SMTP_FROM))
            msg["To"] = to
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
                server.starttls()
                server.login(SMTP_USER, SMTP_PASSWORD)
                server.sendmail(SMTP_FROM, [to], msg.as_string())
            logger.info("Email sent to %s (subject: %s)", to[:50], subject[:50])
            return True
        except Exception as e:
            logger.exception("SMTP send failed: %s", e)
            return False
    if DEV_MODE:
        logger.info(
            "[DEV] Email no enviado (SMTP no configurado). To=%s Subject=%s\nBody:\n%s",
            to, subject, body_plain[:500] + ("..." if len(body_plain) > 500 else ""),
        )
        return True
    return False
