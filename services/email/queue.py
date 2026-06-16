"""Helper to enqueue email send jobs."""
import base64
from typing import Optional

from services.jobs import enqueue_job
from services.email.types import Attachment


def enqueue_send_email(
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
) -> int:
    """Enqueue an email send job. Returns job id.

    Uses services.jobs.enqueue_job which requires issuer_id as int.
    For system-level emails without a specific issuer, passes 0.
    """
    payload = {
        "to_email": to_email,
        "to_name": to_name,
        "template": template,
        "context": context,
        "reply_to": reply_to,
        "issuer_id": issuer_id,
        "user_id": user_id,
        "email_type": email_type,
        "related_object_type": related_object_type,
        "related_object_id": related_object_id,
    }
    if attachments:
        payload["attachments"] = [
            {
                "filename": a.filename,
                "content_b64": base64.b64encode(a.content_bytes).decode("ascii"),
                "mime_type": a.mime_type,
            }
            for a in attachments
        ]
    return enqueue_job(
        "send_email",
        issuer_id or 0,
        payload,
        max_attempts=3,
    )
