"""Public API for the email subsystem."""
from services.email.sender import send_email
from services.email.types import Attachment, EmailType, EmailStatus

__all__ = ["send_email", "Attachment", "EmailType", "EmailStatus"]
