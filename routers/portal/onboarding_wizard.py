"""Portal onboarding wizard — guides new users through setup steps."""
import logging

from fastapi import Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse

from database import db
from routers.deps import get_portal_issuer
from routers.portal._helpers import render_portal

logger = logging.getLogger(__name__)

# Step definitions
STEPS = [
    {"id": 1, "key": "perfil", "label": "Perfil", "description": "Nombre, RFC y regimen fiscal"},
    {"id": 2, "key": "fiel", "label": "FIEL", "description": "Sube tu .cer y .key"},
    {"id": 3, "key": "manifesto", "label": "Manifesto", "description": "Firma la carta manifesto"},
    {"id": 4, "key": "csd", "label": "CSD", "description": "Certificado de sello digital"},
    {"id": 5, "key": "factura", "label": "Primera factura", "description": "Emite tu primera factura"},
]


def register_onboarding_wizard_routes(router, templates):
    """Register onboarding wizard routes."""

    def _render_portal(request, **kwargs):
        return render_portal(templates, request, **kwargs)

    @router.get("/onboarding", response_class=HTMLResponse)
    def portal_onboarding(
        request: Request,
        issuer: dict = Depends(get_portal_issuer),
    ):
        current_step = _get_onboarding_step(issuer)
        step_status = _compute_step_status(issuer)
        return _render_portal(
            request, issuer=issuer,
            template_name="onboarding_wizard.html",
            active_page="onboarding",
            title="Configuracion inicial",
            extra={
                "steps": STEPS,
                "current_step": current_step,
                "step_status": step_status,
            },
        )

    @router.post("/onboarding/skip")
    def portal_onboarding_skip(
        request: Request,
        issuer: dict = Depends(get_portal_issuer),
    ):
        """Dismiss the onboarding wizard."""
        conn = db()
        try:
            conn.execute(
                "UPDATE issuers SET onboarding_dismissed = 1 WHERE id = ?",
                (issuer["id"],),
            )
            conn.commit()
        finally:
            conn.close()
        return JSONResponse({"ok": True})

    @router.post("/onboarding/advance")
    def portal_onboarding_advance(
        request: Request,
        issuer: dict = Depends(get_portal_issuer),
    ):
        """Advance to the next onboarding step."""
        current = _get_onboarding_step(issuer)
        new_step = min(current + 1, 5)
        conn = db()
        try:
            conn.execute(
                "UPDATE issuers SET onboarding_step = ? WHERE id = ?",
                (new_step, issuer["id"]),
            )
            conn.commit()
        finally:
            conn.close()
        return JSONResponse({"ok": True, "step": new_step})


def _get_onboarding_step(issuer: dict) -> int:
    """Get current onboarding step, computing from actual state."""
    from database import db_rows

    issuer_id = issuer.get("id", 0)
    if not issuer_id:
        return 1

    # Check actual completion state
    step = 1

    # Step 1: Profile — has RFC and regimen
    if issuer.get("rfc") and issuer.get("regimen_fiscal"):
        step = 2

    # Step 2: FIEL — has sat_credentials
    creds = db_rows(
        "SELECT 1 FROM sat_credentials WHERE issuer_id = ? AND validation_ok = 1 LIMIT 1",
        (issuer_id,),
    )
    if creds:
        step = max(step, 3)

    # Step 3: Manifesto — check facturapi org exists
    if issuer.get("facturapi_org_id"):
        step = max(step, 4)

    # Step 4: CSD — check if CSD is uploaded (facturapi_live)
    if issuer.get("facturapi_live"):
        step = max(step, 5)

    # Step 5: First invoice
    invoices = db_rows(
        "SELECT 1 FROM invoices WHERE issuer_id = ? LIMIT 1",
        (issuer_id,),
    )
    if invoices:
        step = max(step, 6)  # Completed all steps

    return step


def _compute_step_status(issuer: dict) -> dict:
    """Return a dict mapping step_id → 'done' | 'current' | 'pending'."""
    current = _get_onboarding_step(issuer)
    result = {}
    for s in STEPS:
        if s["id"] < current:
            result[s["id"]] = "done"
        elif s["id"] == current:
            result[s["id"]] = "current"
        else:
            result[s["id"]] = "pending"
    return result
