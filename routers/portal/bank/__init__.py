"""Bank routes package — splits the monolithic bank.py into sub-modules."""
from routers.portal.bank.accounts import register_bank_accounts_routes
from routers.portal.bank.ingest import register_bank_ingest_routes
from routers.portal.bank.movements_crud import register_bank_movements_crud_routes
from routers.portal.bank.movements_export import register_bank_movements_export_routes
from routers.portal.bank.movements_list import register_bank_movements_list_routes
from routers.portal.bank.pages import register_bank_pages_routes
from routers.portal.bank.pdf_preview import register_bank_pdf_preview_routes
from routers.portal.bank.pdf_upload import register_bank_pdf_upload_routes
from routers.portal.bank.preview_ops import register_bank_preview_ops_routes
from routers.portal.bank.statements_list import register_bank_statements_list_routes


def register_bank_routes(router, templates):
    """Register all bank routes on the portal router."""
    register_bank_pages_routes(router, templates)
    register_bank_pdf_preview_routes(router, templates)
    register_bank_accounts_routes(router, templates)
    register_bank_ingest_routes(router, templates)
    register_bank_movements_crud_routes(router, templates)
    register_bank_pdf_upload_routes(router, templates)
    register_bank_preview_ops_routes(router, templates)
    register_bank_statements_list_routes(router, templates)
    register_bank_movements_list_routes(router, templates)
    register_bank_movements_export_routes(router, templates)
