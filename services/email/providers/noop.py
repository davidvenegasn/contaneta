"""Noop provider: logs but doesn't send. Used in dev without API key."""
import logging
import uuid

from services.email.providers.base import EmailProvider
from services.email.types import EmailMessage, SendResult

logger = logging.getLogger(__name__)


class NoopProvider(EmailProvider):
    name = "noop"

    def send(self, message: EmailMessage) -> SendResult:
        msg_id = f"noop-{uuid.uuid4().hex[:12]}"
        logger.info(
            "EMAIL[noop] to=%s subject=%r attachments=%d",
            message.to_email, message.subject, len(message.attachments),
        )
        return SendResult(success=True, provider_message_id=msg_id)
