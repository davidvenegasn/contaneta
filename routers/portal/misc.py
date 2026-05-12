"""Portal misc routes."""
import logging

from fastapi import Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from routers.deps import get_portal_issuer
from routers.portal._helpers import (
    render_portal,
)
from services.auth import csrf as csrf_service
from services.billing import subscription as subscription_service
from services.redirects import safe_next_url
from services.sat.sat_sync import get_month_totals, get_sat_sync_status

logger = logging.getLogger(__name__)

_get_month_totals = get_month_totals
_get_sat_sync_status = get_sat_sync_status


def register_misc_routes(router, templates):
    """Register Misc routes on the portal router."""

    def _render_portal(request, **kwargs):
        return render_portal(templates, request, **kwargs)

    @router.get("/plan", response_class=HTMLResponse)
    def portal_plan(request: Request, issuer: dict = Depends(get_portal_issuer), success: str = Query(""), canceled: str = Query("")):
        user_id = getattr(request.state, "user_id", None) or 0
        issuer_id = int(issuer.get("id") or 0)
        subscription = subscription_service.get_subscription_by_user_id(user_id) if user_id else None
        is_active = subscription_service.is_subscription_active(user_id)
        from services.billing import plans as plans_service
        plan_summary = plans_service.get_plan_summary(issuer_id) if issuer_id > 0 else {
            "plan": "free", "plan_label": "Gratis", "price_mxn": 0,
            "limits": {"invoices": {"used": 0, "limit": 5}, "sat_syncs": {"used": 0, "limit": 0}, "bank_imports": {"used": 0, "limit": 2}, "bank_accounts": {"limit": 1}, "month_close": False, "matching": False},
            "all_plans": plans_service.get_all_plans() if issuer_id > 0 else {},
        }
        # Ensure all_plans always has data
        if not plan_summary.get("all_plans"):
            plan_summary["all_plans"] = {k: {"label": v["label"], "price_mxn": v["price_mxn"], "invoices": v["invoices_per_month"], "sat_syncs": v["sat_syncs_per_month"]} for k, v in plans_service.PLANS.items()}
        return _render_portal(
            request,
            issuer=issuer,
            template_name="portal_plan.html",
            active_page="plan",
            title="Mi plan",
            extra={
                "subscription": subscription,
                "is_active": is_active,
                "success": success == "1",
                "canceled": canceled == "1",
                "plan_summary": plan_summary,
            },
        )

    @router.get("/info", response_class=RedirectResponse)
    def portal_info():
        """Redirige a la página pública de seguridad (misma para usuarios y visitantes)."""
        return RedirectResponse(url="/seguridad", status_code=302)

    @router.post("/notifications/{notification_id}/read", response_class=RedirectResponse)
    def portal_notification_mark_read(
        request: Request,
        notification_id: int,
        issuer: dict = Depends(get_portal_issuer),
        next: str = Form("/portal/home"),
        csrf_token: str | None = Form(None),
    ):
        token_val = (csrf_token or request.headers.get("X-CSRF-Token") or "").strip()
        if not csrf_service.verify_csrf_token(token_val):
            raise HTTPException(status_code=403, detail="Token CSRF inválido o expirado")
        issuer_id = int(issuer.get("id") or 0)
        if issuer_id <= 0:
            raise HTTPException(status_code=401, detail="Sesión inválida")
        from services import notifications as notifications_service

        notifications_service.mark_read(int(issuer_id), int(notification_id))
        return RedirectResponse(url=safe_next_url(next), status_code=302)

    @router.get("/guides", response_class=HTMLResponse)
    def portal_guides(request: Request, issuer: dict = Depends(get_portal_issuer)):
        return _render_portal(
            request,
            issuer=issuer,
            template_name="portal_guides.html",
            active_page="guides",
            title="Guías y tutoriales",
        )

