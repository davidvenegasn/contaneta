"""Fiscal API routes — CFDI deductibility."""
import logging

from fastapi import Body, Depends, HTTPException

from database import db_rows
from routers.deps import get_portal_issuer
from services.http import ok
from services.tenant import require_issuer_id

logger = logging.getLogger(__name__)


def register_fiscal_routes(router):
    """Register fiscal API routes."""

    @router.post("/cfdi/{uuid}/deductibility")
    def api_set_cfdi_deductibility(
        uuid: str,
        issuer: dict = Depends(get_portal_issuer),
        percentage: float = Body(..., embed=True),
    ):
        """Update deductibility percentage for a CFDI."""
        issuer_id = require_issuer_id(issuer)

        if percentage < 0 or percentage > 100:
            raise HTTPException(status_code=400, detail="percentage must be 0-100")

        # Verify CFDI belongs to this issuer (multi-tenancy)
        cfdi = db_rows(
            "SELECT uuid FROM sat_cfdi WHERE issuer_id = ? AND uuid = ? LIMIT 1",
            (issuer_id, uuid),
        )
        if not cfdi:
            raise HTTPException(status_code=404, detail="CFDI not found")

        from services.fiscal.deductibility import set_deductibility
        set_deductibility(issuer_id, uuid, percentage, source="manual")

        return ok({"uuid": uuid, "percentage": percentage, "source": "manual"})
