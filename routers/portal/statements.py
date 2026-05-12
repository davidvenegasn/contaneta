"""Portal financial statements routes — Estado de Resultados and Balance General."""
import csv
import io
import logging

from fastapi import Depends, Query, Request
from fastapi.responses import HTMLResponse, Response

from routers.deps import get_portal_issuer
from routers.portal._helpers import render_portal, ym_now
from services.fiscal.statements import balance_summary, income_statement
from services.ym_helpers import sanitize_ym, shift_ym, ym_to_label

logger = logging.getLogger(__name__)


def register_statements_routes(router, templates):
    """Register financial statements routes on the portal router."""

    def _render_portal(request, **kwargs):
        return render_portal(templates, request, **kwargs)

    @router.get("/estados-financieros", response_class=HTMLResponse)
    def portal_estados_financieros(
        request: Request,
        issuer: dict = Depends(get_portal_issuer),
        ym: str | None = Query(None),
    ):
        """Financial statements page — income statement + balance sheet."""
        try:
            issuer_id = issuer["id"]
            if not ym:
                ym = ym_now()
            ym = sanitize_ym(ym, ym_now())

            stmt = income_statement(issuer_id, ym)
            balance = balance_summary(issuer_id, ym)

            return _render_portal(
                request,
                issuer=issuer,
                template_name="portal_statements.html",
                active_page="estados_financieros",
                title="Estados Financieros",
                extra={
                    "ym": ym,
                    "ym_label": ym_to_label(ym),
                    "prev_ym": shift_ym(ym, -1),
                    "next_ym": shift_ym(ym, 1),
                    "stmt": stmt,
                    "balance": balance,
                },
            )
        except Exception:
            logger.exception("portal: error renderizando /portal/estados-financieros")
            raise

    @router.get("/estados-financieros/csv")
    def portal_estados_financieros_csv(
        request: Request,
        issuer: dict = Depends(get_portal_issuer),
        ym: str | None = Query(None),
        tab: str = Query("income"),
    ):
        """Export financial statements as CSV."""
        issuer_id = issuer["id"]
        if not ym:
            ym = ym_now()
        ym = sanitize_ym(ym, ym_now())

        output = io.StringIO()
        writer = csv.writer(output)

        if tab == "balance":
            b = balance_summary(issuer_id, ym)
            a = b.get("assets", {})
            li = b.get("liabilities", {})
            eq = b.get("equity", {})
            writer.writerow(["Balance General Estimado", ym_to_label(ym)])
            writer.writerow([])
            writer.writerow(["ACTIVOS", ""])
            writer.writerow(["Cuentas por cobrar", f"{a.get('cuentas_por_cobrar', 0):.2f}"])
            writer.writerow(["Saldo estimado en banco", f"{a.get('saldo_estimado_banco', 0):.2f}"])
            writer.writerow(["Total Activos", f"{a.get('total', 0):.2f}"])
            writer.writerow([])
            writer.writerow(["PASIVOS", ""])
            writer.writerow(["Cuentas por pagar", f"{li.get('cuentas_por_pagar', 0):.2f}"])
            writer.writerow(["Impuestos por pagar", f"{li.get('impuestos_por_pagar', 0):.2f}"])
            writer.writerow(["Total Pasivos", f"{li.get('total', 0):.2f}"])
            writer.writerow([])
            writer.writerow(["CAPITAL", ""])
            writer.writerow(["Utilidad acumulada", f"{eq.get('utilidad_acumulada', 0):.2f}"])
            writer.writerow(["Total Capital", f"{eq.get('total', 0):.2f}"])
            filename = f"balance_{ym}.csv"
        else:
            s = income_statement(issuer_id, ym)
            m = s.get("month", {})
            y = s.get("ytd", {})
            writer.writerow(["Estado de Resultados Estimado", ym_to_label(ym)])
            writer.writerow([])
            writer.writerow(["Concepto", "Mes", "Acumulado"])
            writer.writerow(["Ingresos", f"{m.get('ingresos', 0):.2f}", f"{y.get('ingresos', 0):.2f}"])
            writer.writerow(["(-) Gastos deducibles", f"{m.get('gastos', 0):.2f}", f"{y.get('gastos', 0):.2f}"])
            writer.writerow(["Utilidad bruta", f"{m.get('utilidad_bruta', 0):.2f}", f"{y.get('utilidad_bruta', 0):.2f}"])
            writer.writerow(["(-) ISR estimado", f"{m.get('isr_estimado', 0):.2f}", f"{y.get('isr_estimado', 0):.2f}"])
            writer.writerow(["IVA cobrado", f"{m.get('iva_cobrado', 0):.2f}", f"{y.get('iva_cobrado', 0):.2f}"])
            writer.writerow(["IVA pagado", f"{m.get('iva_pagado', 0):.2f}", f"{y.get('iva_pagado', 0):.2f}"])
            writer.writerow(["IVA neto", f"{m.get('iva_neto', 0):.2f}", f"{y.get('iva_neto', 0):.2f}"])
            writer.writerow(["Utilidad neta", f"{m.get('utilidad_neta', 0):.2f}", f"{y.get('utilidad_neta', 0):.2f}"])
            filename = f"estado_resultados_{ym}.csv"

        writer.writerow([])
        writer.writerow(["Estimacion contable aproximada. NO sustituye contabilidad formal ni asesoria profesional."])

        content = output.getvalue()
        return Response(
            content=content,
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
