"""Inbound webhooks from third-party services (Facturapi, etc.)."""
from fastapi import APIRouter

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])

from routers.api.webhooks import facturapi as _facturapi  # noqa: E402,F401
