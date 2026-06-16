"""Email system types and enums."""
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class EmailType(str, Enum):
    INVOICE_SENT = "invoice_sent"
    DECLARATION_SUMMARY = "declaration_summary"
    WELCOME = "welcome"
    EMAIL_VERIFICATION = "email_verification"
    PASSWORD_RESET = "password_reset"
    CSD_EXPIRING = "csd_expiring"
    FIEL_EXPIRING = "fiel_expiring"
    TRIAL_EXPIRING = "trial_expiring"
    SUBSCRIPTION_RENEWED = "subscription_renewed"
    PAYMENT_FAILED = "payment_failed"


class EmailStatus(str, Enum):
    QUEUED = "queued"
    SENT = "sent"
    DELIVERED = "delivered"
    OPENED = "opened"
    CLICKED = "clicked"
    BOUNCED = "bounced"
    FAILED = "failed"


@dataclass
class Attachment:
    filename: str
    content_bytes: bytes
    mime_type: str = "application/octet-stream"


@dataclass
class EmailMessage:
    """Outbound email message — all fields the providers need."""
    to_email: str
    subject: str
    html_body: str
    text_body: Optional[str] = None
    to_name: Optional[str] = None
    from_email: Optional[str] = None
    from_name: Optional[str] = None
    reply_to: Optional[str] = None
    attachments: list[Attachment] = field(default_factory=list)
    tags: dict[str, str] = field(default_factory=dict)


@dataclass
class SendResult:
    success: bool
    provider_message_id: Optional[str] = None
    error_message: Optional[str] = None
