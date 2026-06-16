"""Email system configuration from env vars."""
import os
from typing import Literal

ProviderName = Literal["noop", "resend"]


def get_provider_name() -> ProviderName:
    """Return active provider. Defaults to 'noop' if RESEND_API_KEY missing."""
    explicit = os.getenv("EMAIL_PROVIDER", "").strip().lower()
    if explicit in ("noop", "resend"):
        return explicit  # type: ignore
    if os.getenv("RESEND_API_KEY"):
        return "resend"
    return "noop"


def get_default_from_address() -> str:
    return os.getenv("EMAIL_FROM_ADDRESS", "noreply@example.com")


def get_default_from_name() -> str:
    return os.getenv("EMAIL_FROM_NAME", "ContaNeta")


def get_resend_api_key() -> str:
    return os.getenv("RESEND_API_KEY", "")


def get_resend_webhook_secret() -> str:
    return os.getenv("RESEND_WEBHOOK_SECRET", "")


def is_dev_mode() -> bool:
    return os.getenv("ENV", "dev").lower() == "dev"
