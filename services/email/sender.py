"""Main send_email() entry point."""
import logging
from typing import Optional

from services.email import config, log, templates
from services.email.providers.base import EmailProvider
from services.email.providers.noop import NoopProvider
from services.email.providers.resend import ResendProvider
from services.email.types import Attachment, EmailMessage

logger = logging.getLogger(__name__)


SUBJECTS_BY_TEMPLATE = {
    "invoice_sent": "{from_name} te emitió una factura por ${total}",
    "declaration_summary": "Tu declaración de {periodo} está lista",
    "welcome": "Bienvenido a ContaNeta",
    "email_verification": "Verifica tu correo",
    "password_reset": "Restablecer contraseña",
    "csd_expiring": "Tu CSD vence pronto",
    "fiel_expiring": "Tu FIEL vence pronto",
    "trial_expiring": "Tu trial termina en {days} días",
    "subscription_renewed": "Suscripción renovada",
    "payment_failed": "No pudimos procesar tu pago",
}


def _get_provider() -> EmailProvider:
    name = config.get_provider_name()
    if name == "resend":
        return ResendProvider()
    return NoopProvider()


def send_email(
    *,
    to_email: str,
    template: str,
    context: dict,
    to_name: Optional[str] = None,
    reply_to: Optional[str] = None,
    attachments: Optional[list[Attachment]] = None,
    issuer_id: Optional[int] = None,
    user_id: Optional[int] = None,
    email_type: Optional[str] = None,
    related_object_type: Optional[str] = None,
    related_object_id: Optional[int] = None,
    subject_override: Optional[str] = None,
) -> int:
    """Send an email synchronously and log the attempt.

    Returns email_log id. Caller should typically enqueue this via the jobs
    queue instead of calling directly, except for time-critical flows
    (password reset, email verification).
    """
    # Render
    try:
        html, text = templates.render(template, context)
    except Exception as exc:
        logger.exception("Template render failed for %s", template)
        log_id = log.insert_log(
            email_type=email_type or template,
            to_email=to_email,
            to_name=to_name,
            issuer_id=issuer_id, user_id=user_id,
            related_object_type=related_object_type, related_object_id=related_object_id,
            template=template,
            payload_context=context,
            status="failed",
        )
        log.mark_failed(log_id, f"render error: {exc}")
        return log_id

    # Subject
    if subject_override:
        subject = subject_override
    else:
        subject_template = SUBJECTS_BY_TEMPLATE.get(template, "Notificación de ContaNeta")
        try:
            subject = subject_template.format(**context)
        except Exception:
            subject = subject_template

    from_email = config.get_default_from_address()
    from_name = context.get("brand_name") or config.get_default_from_name()

    # Insert log row first (queued state)
    provider = _get_provider()
    log_id = log.insert_log(
        email_type=email_type or template,
        to_email=to_email,
        to_name=to_name,
        from_email=from_email,
        from_name=from_name,
        reply_to=reply_to,
        subject=subject,
        template=template,
        provider=provider.name,
        issuer_id=issuer_id, user_id=user_id,
        related_object_type=related_object_type, related_object_id=related_object_id,
        payload_context=context,
        status="queued",
    )

    msg = EmailMessage(
        to_email=to_email,
        to_name=to_name,
        subject=subject,
        html_body=html,
        text_body=text,
        from_email=from_email,
        from_name=from_name,
        reply_to=reply_to,
        attachments=attachments or [],
        tags={"template": template, "type": email_type or template},
    )

    result = provider.send(msg)
    if result.success:
        log.mark_sent(log_id, provider_message_id=result.provider_message_id)
    else:
        log.mark_failed(log_id, result.error_message or "unknown error")

    return log_id
