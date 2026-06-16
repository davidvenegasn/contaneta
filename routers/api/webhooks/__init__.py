"""Inbound webhooks from third-party services (Facturapi, Resend, etc.)."""
from fastapi import APIRouter

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])

from routers.api.webhooks import facturapi as _facturapi  # noqa: E402,F401
from routers.api.webhooks import resend as _resend  # noqa: E402,F401
