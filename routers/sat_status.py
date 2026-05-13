"""SAT connection status API endpoint."""

import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from routers.deps import get_portal_issuer
from services import sat_status as sat_status_service
from services.http import ok

logger = logging.getLogger(__name__)

router = APIRouter(tags=["sat-status"])


@router.get("/portal/sat/status")
def portal_sat_status(request: Request, issuer: dict = Depends(get_portal_issuer)):
    """Return SAT connection status as JSON for the authenticated issuer.

    Response keys: connected, fiel_expires_at, fiel_days_remaining,
    last_sync_at, last_sync_status, invoices_synced, fiel_warning,
    sync_history.
    """
    issuer_id = issuer["id"]
    status = sat_status_service.get_sat_connection_status(issuer_id)
    warning = sat_status_service.check_fiel_expiry_warning(issuer_id)
    history = sat_status_service.get_sync_history(issuer_id, limit=5)
    return ok({
        **status,
        "fiel_warning": warning,
        "sync_history": history,
    })
