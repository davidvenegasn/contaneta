"""Portal router package — re-exports get_portal_router for app.py compatibility."""
from routers.portal._monolith import get_portal_router

__all__ = ["get_portal_router"]
