"""Webhook endpoint for Resend email events."""
import hashlib
import hmac
import json
import logging

from fastapi import Header, HTTPException, Request

from routers.api.webhooks import router
from services.email.config import get_resend_webhook_secret
from services.email.log import update_status_by_provider_id

logger = logging.getLogger(__name__)


# Map Resend event type → (email_log.status, timestamp_field)
EVENT_MAP = {
    "email.sent":       ("sent", None),
    "email.delivered":  ("delivered", "delivered_at"),
    "email.opened":     ("opened", "opened_at"),
    "email.clicked":    ("clicked", "clicked_at"),
    "email.bounced":    ("bounced", "bounced_at"),
    "email.complained": ("bounced", "bounced_at"),
    "email.failed":     ("failed", None),
}


def _verify_signature(secret: str, body: bytes, signature: str) -> bool:
    """Resend uses Svix for webhooks. Verify HMAC-SHA256 over the raw body."""
    if not secret or not signature:
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


@router.post("/resend")
async def resend_webhook(
    request: Request,
    svix_signature: str = Header(default="", alias="svix-signature"),
):
    """Receive Resend webhook events and update email_log."""
    body = await request.body()
    secret = get_resend_webhook_secret()
    if secret and not _verify_signature(secret, body, svix_signature):
        raise HTTPException(status_code=401, detail="Invalid signature")

    try:
        event = json.loads(body)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    event_type = event.get("type", "")
    data = event.get("data", {}) or {}
    provider_message_id = data.get("email_id") or data.get("id")
    if not provider_message_id:
        logger.warning("Resend webhook missing email id: %s", event_type)
        return {"ok": True, "ignored": True}

    mapping = EVENT_MAP.get(event_type)
    if not mapping:
        logger.info("Resend webhook unmapped event: %s", event_type)
        return {"ok": True, "ignored": True}

    status, ts_field = mapping
    affected = update_status_by_provider_id(provider_message_id, status, ts_field)
    return {"ok": True, "affected": affected}
