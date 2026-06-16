"""Portal quotations routes."""
import logging

from fastapi import Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, Response

from database import db
from routers.deps import get_portal_issuer
from routers.portal._helpers import (
    render_portal,
)
from services import audit
from services import quotations as quotations_service
from services.action_log import log_action
from services.auth import session as session_service
from services.sat.sat_sync import get_month_totals, get_sat_sync_status

logger = logging.getLogger(__name__)

_get_month_totals = get_month_totals
_get_sat_sync_status = get_sat_sync_status


def register_quotations_routes(router, templates):
    """Register Quotations routes on the portal router."""

    def _render_portal(request, **kwargs):
        return render_portal(templates, request, **kwargs)

    def _portal_quotations_impl(request: Request, issuer: dict):
        try:
            return _render_portal(
                request,
                issuer=issuer,
                template_name="portal_quotations.html",
                active_page="quotations",
                title="Cotizaciones",
            )
        except Exception:
            logger.exception("portal: error renderizando cotizaciones")
            raise

    @router.get("/quotations", response_class=HTMLResponse)
    @router.get("/cotizaciones", response_class=HTMLResponse)
    def portal_quotations(request: Request, issuer: dict = Depends(get_portal_issuer)):
        return _portal_quotations_impl(request, issuer)

    @router.get("/cotizaciones/ping")
    def portal_cotizaciones_ping():
        return Response(content="cotizaciones-ok", media_type="text/plain")

    @router.get("/quotations/{qid}/pdf")
    def portal_quotation_pdf(
        request: Request,
        qid: int,
        issuer: dict = Depends(get_portal_issuer),
        download: str = Query("0", alias="download"),
    ):
        conn = db()
        row = conn.execute(
            "SELECT id, public_token FROM quotations WHERE issuer_id = ? AND id = ?",
            (issuer["id"], qid),
        ).fetchone()
        if not row:
            conn.close()
            raise HTTPException(status_code=404, detail="Cotización no encontrada")
        conn.close()
        quote = quotations_service.get_quotation_by_public_token(dict(row)["public_token"])
        if not quote:
            raise HTTPException(status_code=404, detail="Cotización no encontrada")
        cookie_val = request.cookies.get(session_service.get_session_cookie_name())
        data = session_service.verify_session(cookie_val)
        uid = data[0] if data and len(data) >= 1 else None
        audit.log(action="quotation_pdf", user_id=uid, issuer_id=issuer["id"], details=f"qid={qid}")
        log_action(request, "quotation_pdf", issuer_id=issuer["id"], quotation_id=qid)
        try:
            pdf_bytes = quotations_service.build_quotation_pdf(quote)
        except Exception:
            logger.exception("portal: error generando PDF de cotización qid=%s", qid)
            raise
        disposition = "attachment" if download == "1" else "inline"
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'{disposition}; filename="cotizacion-{qid}.pdf"'},
        )

    @router.get("/quotations/{qid}", response_class=HTMLResponse)
    def portal_quotation_detail(request: Request, qid: int, issuer: dict = Depends(get_portal_issuer)):
        conn = db()
        row = conn.execute(
            "SELECT id, public_token, folio, customer_rfc, customer_legal_name, customer_email, status, notes, responded_at, created_at, converted_invoice_id, converted_at FROM quotations WHERE issuer_id = ? AND id = ?",
            (issuer["id"], qid),
        ).fetchone()
        conn.close()
        if not row:
            raise HTTPException(status_code=404, detail="Cotización no encontrada")
        d = dict(row)
        quote = quotations_service.get_quotation_by_public_token(d["public_token"])
        if not quote:
            raise HTTPException(status_code=404, detail="Cotización no encontrada")
        return _render_portal(
            request,
            issuer=issuer,
            template_name="quote_detail.html",
            active_page="quotations",
            title="Cotización",
            extra={"quote": quote},
        )

