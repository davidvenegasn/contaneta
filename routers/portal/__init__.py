"""Portal router package — assembles feature sub-modules into one router."""
from fastapi import APIRouter


def get_portal_router(templates):
    """Build portal router with all /portal/* HTML routes. Requires Jinja2 templates instance."""
    router = APIRouter(prefix="/portal", tags=["portal"])

    from routers.portal.bank import register_bank_routes
    from routers.portal.catalogs import register_catalogs_routes
    from routers.portal.dashboard import register_dashboard_routes
    from routers.portal.facturapi_setup import register_facturapi_setup_routes
    from routers.portal.fiscal import register_fiscal_routes
    from routers.portal.invoices import register_invoices_routes
    from routers.portal.misc import register_misc_routes
    from routers.portal.month_close import register_month_close_routes
    from routers.portal.quotations import register_quotations_routes
    from routers.portal.sat_config import register_sat_config_routes
    from routers.portal.settings import register_settings_routes
    from routers.portal.audit_log import register_audit_log_routes
    from routers.portal.constancia import register_constancia_routes
    from routers.portal.declarations import register_declarations_routes
    from routers.portal.onboarding_wizard import register_onboarding_wizard_routes
    from routers.portal.reports import register_reports_routes
    from routers.portal.statements import register_statements_routes
    from routers.portal.team import register_team_routes

    register_dashboard_routes(router, templates)
    register_quotations_routes(router, templates)
    register_invoices_routes(router, templates)
    register_catalogs_routes(router, templates)
    register_bank_routes(router, templates)
    register_month_close_routes(router, templates)
    register_sat_config_routes(router, templates)
    register_fiscal_routes(router, templates)
    register_statements_routes(router, templates)
    register_settings_routes(router, templates)
    register_facturapi_setup_routes(router, templates)
    register_reports_routes(router, templates)
    register_declarations_routes(router, templates)
    register_onboarding_wizard_routes(router, templates)
    register_audit_log_routes(router, templates)
    register_constancia_routes(router, templates)
    register_team_routes(router, templates)
    register_misc_routes(router, templates)

    return router
