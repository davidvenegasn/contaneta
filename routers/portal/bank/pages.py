"""Bank pages — redirects and landing pages."""
import logging

from fastapi import Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from routers.deps import get_portal_issuer
from routers.portal._helpers import render_portal
from services.auth import csrf as csrf_service

logger = logging.getLogger(__name__)


def register_bank_pages_routes(router, templates):
    """Register bank page/redirect routes."""

    def _render_portal(request, **kwargs):
        return render_portal(templates, request, **kwargs)

    @router.get("/bancos", response_class=RedirectResponse)
    def portal_bancos_redirect():
        """Redirigir a la pagina de convertir estado de cuenta."""
        return RedirectResponse(url="/portal/convertir-edo-cuenta", status_code=302)

    @router.get("/convertir-edo-cuenta", response_class=HTMLResponse)
    def portal_convertir_edo_cuenta(request: Request, issuer: dict = Depends(get_portal_issuer)):
        """Pagina unica: arrastrar PDF, convertir a Excel y ver movimientos (sin pestanas ni hub)."""
        try:
            return _render_portal(
                request,
                issuer=issuer,
                template_name="portal_bank_pdf_to_excel.html",
                active_page="convertir_edo_cuenta",
                title="Convertir Edo. de Cuenta",
            )
        except Exception as e:
            logger.exception("convertir-edo-cuenta: error en render completo (%s), usando pagina minima", e)
            try:
                return templates.TemplateResponse(
                    request,
                    "portal_convertir_edo_cuenta_minimal.html",
                    {
                        "csrf_token": csrf_service.generate_csrf_token(),
                        "preview_movements": [],
                        "preview_summary": {},
                    },
                    status_code=200,
                )
            except Exception as e2:
                logger.exception("convertir-edo-cuenta: fallback minima tambien fallo: %s", e2)
                raise
