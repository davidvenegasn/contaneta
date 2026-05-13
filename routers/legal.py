"""Public legal pages: privacy policy, terms of service, cookie policy."""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse


def get_legal_router(templates):
    """Create and return the legal pages router.

    Args:
        templates: Jinja2Templates instance for rendering.

    Returns:
        APIRouter with /privacy, /terms, /cookies routes.
    """
    router = APIRouter(tags=["legal"])

    @router.get("/privacy", response_class=HTMLResponse)
    def privacy_page(request: Request):
        """Aviso de Privacidad (LFPDPPP compliant)."""
        return templates.TemplateResponse(
            "legal_privacy.html", {"request": request}
        )

    @router.get("/terms", response_class=HTMLResponse)
    def terms_page(request: Request):
        """Términos y Condiciones del servicio."""
        return templates.TemplateResponse(
            "legal_terms.html", {"request": request}
        )

    @router.get("/cookies", response_class=HTMLResponse)
    def cookies_page(request: Request):
        """Política de Cookies."""
        return templates.TemplateResponse(
            "legal_cookies.html", {"request": request}
        )

    return router
