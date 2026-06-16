"""Resend HTTP provider. Uses Resend REST API directly (no SDK)."""
import base64
import logging
from typing import Any

import httpx

from services.email.config import get_resend_api_key
from services.email.providers.base import EmailProvider
from services.email.types import EmailMessage, SendResult

logger = logging.getLogger(__name__)

RESEND_API_URL = "https://api.resend.com/emails"


class ResendProvider(EmailProvider):
    name = "resend"

    def send(self, message: EmailMessage) -> SendResult:
        api_key = get_resend_api_key()
        if not api_key:
            return SendResult(success=False, error_message="RESEND_API_KEY not configured")

        from_value = (
            f"{message.from_name} <{message.from_email}>"
            if message.from_name and message.from_email
            else (message.from_email or "")
        )
        to_value = (
            f"{message.to_name} <{message.to_email}>"
            if message.to_name
            else message.to_email
        )

        payload: dict[str, Any] = {
            "from": from_value,
            "to": [to_value],
            "subject": message.subject,
            "html": message.html_body,
        }
        if message.text_body:
            payload["text"] = message.text_body
        if message.reply_to:
            payload["reply_to"] = [message.reply_to]
        if message.tags:
            payload["tags"] = [{"name": k, "value": v} for k, v in message.tags.items()]
        if message.attachments:
            payload["attachments"] = [
                {
                    "filename": a.filename,
                    "content": base64.b64encode(a.content_bytes).decode("ascii"),
                }
                for a in message.attachments
            ]

        try:
            with httpx.Client(timeout=20.0) as client:
                resp = client.post(
                    RESEND_API_URL,
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
            if resp.status_code >= 400:
                return SendResult(
                    success=False,
                    error_message=f"Resend {resp.status_code}: {resp.text[:300]}",
                )
            data = resp.json()
            return SendResult(success=True, provider_message_id=data.get("id"))
        except Exception as exc:
            logger.exception("Resend send failed")
            return SendResult(success=False, error_message=str(exc))
