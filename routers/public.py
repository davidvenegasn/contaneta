"""Rutas públicas: cotización por link (/q/{token}, /public/cotizacion), /pricing."""
from datetime import datetime

from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from database import db
from services import quotations
from services.billing.plans import PLANS


def get_public_router(templates):
    router = APIRouter()

    @router.get("/demo", response_class=HTMLResponse)
    def demo_page(request: Request):
        """Página demo interactiva: tabs SAT Sync, Emitidas, Factura rápida, Cotizaciones; mock UI + CTA al portal."""
        return templates.TemplateResponse(request, "demo.html", {})

    @router.get("/pricing", response_class=HTMLResponse)
    def pricing_page(request: Request, reason: str | None = Query(None)):
        """Página de planes. CTA a /signup. Sin Stripe aún; lista para añadirlo después."""
        return templates.TemplateResponse(
            request,
            "pricing.html",
            {
                "reason": reason,
                "trial_expired": reason == "trial_expired",
                "plans": PLANS,
            },
        )

    @router.get("/comparar", response_class=RedirectResponse)
    def compare_redirect():
        """Redirige al comparador de planes (sección en /pricing)."""
        return RedirectResponse(url="/pricing#comparar", status_code=302)

    @router.get("/seguridad", response_class=HTMLResponse)
    def seguridad_page(request: Request):
        """Página de seguridad tipo fintech: sesiones, aislamiento por cuenta, FIEL solo para sync; enlaces a términos y privacidad."""
        return templates.TemplateResponse(request, "seguridad.html", {})

    @router.get("/trust", response_class=RedirectResponse)
    @router.get("/security", response_class=RedirectResponse)
    def trust_alias():
        """Aliases para marketing / SEO."""
        return RedirectResponse(url="/seguridad", status_code=302)

    @router.get("/q/{public_token}/pdf")
    def public_quotation_pdf(public_token: str):
        quote = quotations.get_quotation_by_public_token(public_token)
        if not quote:
            return HTMLResponse("<p>Cotización no encontrada.</p>", status_code=404)
        try:
            pdf_bytes = quotations.build_quotation_pdf(quote)
        except Exception as e:
            return HTMLResponse(f"<p>Error generando PDF: {e}</p>", status_code=500)
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'inline; filename="cotizacion-{public_token[:8]}.pdf"'},
        )

    @router.get("/q/{public_token}", response_class=HTMLResponse)
    @router.get("/public/cotizacion/{public_token}", response_class=HTMLResponse)
    def public_quotation_view(request: Request, public_token: str):
        quote = quotations.get_quotation_by_public_token(public_token)
        if not quote:
            return HTMLResponse(
                "<!DOCTYPE html><html><head><meta charset='utf-8'><title>No encontrada</title></head><body><p>Cotización no encontrada o link expirado.</p></body></html>",
                status_code=404,
            )
        if quote["status"] not in ("draft", "sent"):
            return templates.TemplateResponse(
                request,
                "public_quotation_responded.html",
                {"quotation": quote},
            )
        return templates.TemplateResponse(
            request,
            "public_quotation.html",
            {"quotation": quote},
        )

    @router.post("/public/cotizacion/respond", response_class=HTMLResponse)
    def public_quotation_respond(
        request: Request,
        public_token: str = Form(alias="public_token", default=""),
        action: str = Form(default=""),
        rejection_reason: str = Form(default=""),
    ):
        token = (public_token or "").strip()
        act = (action or request.form.get("action") or "").strip().lower()
        if not token:
            return HTMLResponse("<p>Link inválido.</p>", status_code=400)
        if act not in ("accept", "reject", "aceptar", "rechazar"):
            return HTMLResponse("<p>Acción inválida.</p>", status_code=400)
        status = "accepted" if act in ("accept", "aceptar") else "rejected"
        reason = (rejection_reason or request.form.get("rejection_reason") or "").strip() or None
        client_ip = request.client.host if request.client else None
        user_agent = request.headers.get("user-agent")
        now = datetime.now().isoformat()
        conn = db()
        row = conn.execute("SELECT id, status FROM quotations WHERE public_token = ?", (token,)).fetchone()
        if not row:
            conn.close()
            return HTMLResponse("<p>Cotización no encontrada.</p>", status_code=404)
        if row["status"] not in ("draft", "sent"):
            conn.close()
            quote = quotations.get_quotation_by_public_token(token)
            return templates.TemplateResponse(
                request,
                "public_quotation_responded.html",
                {"quotation": quote or {}},
            )
        qid = row["id"]
        if status == "accepted":
            conn.execute(
                """UPDATE quotations SET status = ?, responded_at = datetime('now'), updated_at = datetime('now'),
                   accepted_at = ?, decision_ip = ?, decision_user_agent = ? WHERE id = ?""",
                (status, now, client_ip, user_agent, qid),
            )
        else:
            conn.execute(
                """UPDATE quotations SET status = ?, responded_at = datetime('now'), updated_at = datetime('now'),
                   rejected_at = ?, decision_ip = ?, decision_user_agent = ?, rejection_reason = ? WHERE id = ?""",
                (status, now, client_ip, user_agent, reason, qid),
            )
        conn.commit()
        conn.close()
        quote = quotations.get_quotation_by_public_token(token)
        return templates.TemplateResponse(
            request,
            "public_quotation_thanks.html",
            {"quotation": quote, "action": status},
        )

    return router
