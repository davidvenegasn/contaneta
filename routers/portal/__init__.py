"""Portal router package — assembles feature sub-modules into one router."""
from fastapi import APIRouter


def get_portal_router(templates):
    """Build portal router with all /portal/* HTML routes. Requires Jinja2 templates instance."""
    router = APIRouter(prefix="/portal", tags=["portal"])

    from routers.portal.bank import register_bank_routes
    from routers.portal.catalogs import register_catalogs_routes
    from routers.portal.dashboard import register_dashboard_routes
    from routers.portal.fiscal import register_fiscal_routes
    from routers.portal.invoices import register_invoices_routes
    from routers.portal.misc import register_misc_routes
    from routers.portal.month_close import register_month_close_routes
    from routers.portal.quotations import register_quotations_routes
    from routers.portal.sat_config import register_sat_config_routes

    register_dashboard_routes(router, templates)
    register_quotations_routes(router, templates)
    register_invoices_routes(router, templates)
    register_catalogs_routes(router, templates)
    register_bank_routes(router, templates)
    register_month_close_routes(router, templates)
    register_sat_config_routes(router, templates)
    register_fiscal_routes(router, templates)
    register_misc_routes(router, templates)

    return router
