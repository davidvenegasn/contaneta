"""API router package — assembles feature sub-modules into one router."""
from fastapi import APIRouter

router = APIRouter(prefix="/api")


def _register_all():
    from routers.api.account import register_account_routes
    from routers.api.catalogs import register_catalogs_routes
    from routers.api.customers import register_customers_routes
    from routers.api.invoices import register_invoices_routes
    from routers.api.operations import register_operations_routes
    from routers.api.products import register_products_routes
    from routers.api.providers import register_providers_routes
    from routers.api.quotations import register_quotations_routes

    register_account_routes(router)
    register_customers_routes(router)
    register_products_routes(router)
    register_invoices_routes(router)
    register_quotations_routes(router)
    register_providers_routes(router)
    register_catalogs_routes(router)
    register_operations_routes(router)


_register_all()
