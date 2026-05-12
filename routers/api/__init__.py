"""API router package — re-exports router for app.py compatibility."""
from routers.api._monolith import router

__all__ = ["router"]
