"""Envío de correos: SMTP si está configurado; en DEV sin SMTP se loguea el link/body."""
import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from typing import Optional

from config import DEV_MODE

logger = logging.getLogger(__name__)
SMTP_HOST = (os.getenv("SMTP_HOST") or "").strip()
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = (os.getenv("SMTP_USER") or "").strip()
SMTP_PASSWORD = (os.getenv("SMTP_PASSWORD") or "").strip()
SMTP_FROM = (os.getenv("SMTP_FROM") or SMTP_USER or "noreply@localhost").strip()
SMTP_REPLY_TO = (os.getenv("SMTP_REPLY_TO") or "").strip()
SMTP_TIMEOUT = int(os.getenv("SMTP_TIMEOUT", "30"))


def is_configured() -> bool:
    """Return True if SMTP credentials are present."""
    return bool(SMTP_HOST and SMTP_USER and SMTP_PASSWORD)


def send_email(to: str, subject: str, body_plain: str, body_html: Optional[str] = None) -> bool:
    """Send an email via SMTP.

    When both body_plain and body_html are provided, sends multipart/alternative
    so email clients can pick the best version. Falls back to dev-mode logging
    when SMTP is not configured.

    Args:
        to: Recipient email address.
        subject: Email subject line.
        body_plain: Plain-text body (required).
        body_html: Optional HTML body for rich rendering.

    Returns:
        True if sent (or logged in DEV mode); False on failure.
    """
    to = (to or "").strip().lower()
    if not to or "@" not in to:
        return False
    if is_configured():
        try:
            if body_html:
                msg = MIMEMultipart("alternative")
                msg.attach(MIMEText(body_plain, "plain", "utf-8"))
                msg.attach(MIMEText(body_html, "html", "utf-8"))
            else:
                msg = MIMEText(body_plain, "plain", "utf-8")
            msg["Subject"] = subject
            msg["From"] = formataddr(("ContaNeta", SMTP_FROM))
            msg["To"] = to
            if SMTP_REPLY_TO:
                msg["Reply-To"] = SMTP_REPLY_TO
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=SMTP_TIMEOUT) as server:
                server.starttls()
                server.login(SMTP_USER, SMTP_PASSWORD)
                server.sendmail(SMTP_FROM, [to], msg.as_string())
            logger.info("Email sent to %s (subject: %s)", to[:50], subject[:50])
            return True
        except smtplib.SMTPAuthenticationError:
            logger.error("SMTP auth failed for %s — check SMTP_USER/SMTP_PASSWORD", SMTP_HOST)
            return False
        except (smtplib.SMTPConnectError, smtplib.SMTPServerDisconnected, TimeoutError, OSError) as e:
            logger.error("SMTP connection error (%s:%s): %s", SMTP_HOST, SMTP_PORT, e)
            return False
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
