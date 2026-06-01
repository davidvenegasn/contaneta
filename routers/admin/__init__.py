"""Admin router package — aggregates all admin submodules."""
from fastapi import APIRouter

from routers.admin.dashboard import register_dashboard_routes
from routers.admin.impersonate import register_impersonate_routes
from routers.admin.issuers import register_issuer_routes
from routers.admin.jobs import register_job_routes
from routers.admin.ops import register_ops_routes
from routers.admin.sat import register_sat_admin_routes


def get_admin_router(templates):
    """Construye el router de admin con rutas HTML y acciones. Requiere Jinja2 templates."""
    router = APIRouter(prefix="/admin", tags=["admin"])

    register_dashboard_routes(router, templates)
    register_issuer_routes(router, templates)
    register_job_routes(router, templates)
    register_ops_routes(router, templates)
    register_impersonate_routes(router, templates)
    register_sat_admin_routes(router, templates)

    return router
