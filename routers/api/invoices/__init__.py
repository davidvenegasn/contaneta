"""Invoices API routes package — splits the monolithic invoices.py into sub-modules."""
from routers.api.invoices.bootstrap import register_invoices_bootstrap_routes
from routers.api.invoices.cancel import register_invoices_cancel_routes
from routers.api.invoices.data import register_invoices_data_routes
from routers.api.invoices.foreign import register_invoices_foreign_routes
from routers.api.invoices.issued_list import register_invoices_issued_routes
from routers.api.invoices.pdf_extract import register_invoices_pdf_extract_routes
from routers.api.invoices.quick_create import register_invoices_quick_routes
from routers.api.invoices.received_list import register_invoices_received_routes


def register_invoices_routes(router):
    """Register all invoice API routes on the router."""
    register_invoices_bootstrap_routes(router)
    register_invoices_quick_routes(router)
    register_invoices_cancel_routes(router)
    register_invoices_data_routes(router)
    register_invoices_issued_routes(router)
    register_invoices_received_routes(router)
    register_invoices_foreign_routes(router)
    register_invoices_pdf_extract_routes(router)
