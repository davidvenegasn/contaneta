"""Admin stats dashboard routes."""
from fastapi import Depends, Request
from fastapi.responses import HTMLResponse

from routers.admin._deps import require_admin_or_owner
from services.admin_stats import get_dashboard_stats
from services.http import ok


def register_stats_routes(router, templates):
    """Register admin stats routes."""

    @router.get("/stats", response_class=HTMLResponse)
    def admin_stats_page(
        request: Request,
        _admin: tuple[int, int, int | None] = Depends(require_admin_or_owner),
    ):
        """Admin stats dashboard with KPI cards."""
        stats = get_dashboard_stats()
        return templates.TemplateResponse(
            request,
            "admin_stats.html",
            {"active_page": "stats", "stats": stats},
        )

    @router.get("/stats.json")
    def admin_stats_json(
        _admin: tuple[int, int, int | None] = Depends(require_admin_or_owner),
    ):
        """Admin stats as JSON for monitoring integrations."""
        return ok(get_dashboard_stats())
