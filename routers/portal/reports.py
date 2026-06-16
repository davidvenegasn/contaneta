"""Portal reports routes — monthly, annual, and PPD cobranza."""
import logging
from datetime import datetime

from fastapi import Depends, Query, Request
from fastapi.responses import HTMLResponse, Response

from routers.deps import get_portal_issuer
from routers.portal._helpers import render_portal, ym_now
from services.ym_helpers import sanitize_ym, ym_to_label

logger = logging.getLogger(__name__)


def register_reports_routes(router, templates):
    """Register report routes on the portal router."""

    def _render_portal(request, **kwargs):
        return render_portal(templates, request, **kwargs)

    @router.get("/reports/monthly", response_class=HTMLResponse)
    def portal_report_monthly(
        request: Request,
        ym: str = Query(None),
        issuer: dict = Depends(get_portal_issuer),
    ):
        if not ym:
            ym = ym_now()
        ym = sanitize_ym(ym, ym_now())
        from services.reports.monthly import build_monthly_report
        report = build_monthly_report(issuer["id"], ym)
        return _render_portal(
            request, issuer=issuer,
            template_name="portal_report_monthly.html",
            active_page="reports",
            title=f"Reporte mensual — {ym_to_label(ym)}",
            extra={
                "report": report,
                "ym": ym,
                "ym_label": ym_to_label(ym),
            },
        )

    @router.get("/reports/monthly/excel")
    def portal_report_monthly_excel(
        request: Request,
        ym: str = Query(None),
        issuer: dict = Depends(get_portal_issuer),
    ):
        if not ym:
            ym = ym_now()
        ym = sanitize_ym(ym, ym_now())
        from services.reports.monthly import build_monthly_report
        from services.reports.exporters import monthly_to_excel
        report = build_monthly_report(issuer["id"], ym)
        excel_bytes = monthly_to_excel(report)
        return Response(
            content=excel_bytes,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="reporte_{ym}.xlsx"'},
        )

    @router.get("/reports/annual", response_class=HTMLResponse)
    def portal_report_annual(
        request: Request,
        year: int = Query(None),
        issuer: dict = Depends(get_portal_issuer),
    ):
        if not year:
            year = datetime.now().year
        from services.reports.annual import build_annual_report
        report = build_annual_report(issuer["id"], year)
        return _render_portal(
            request, issuer=issuer,
            template_name="portal_report_annual.html",
            active_page="reports",
            title=f"Reporte anual — {year}",
            extra={"report": report, "year": year},
        )

    @router.get("/reports/annual/excel")
    def portal_report_annual_excel(
        request: Request,
        year: int = Query(None),
        issuer: dict = Depends(get_portal_issuer),
    ):
        if not year:
            year = datetime.now().year
        from services.reports.annual import build_annual_report
        from services.reports.exporters import annual_to_excel
        report = build_annual_report(issuer["id"], year)
        excel_bytes = annual_to_excel(report)
        return Response(
            content=excel_bytes,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="reporte_anual_{year}.xlsx"'},
        )

    @router.get("/reports/ppd-cobranza", response_class=HTMLResponse)
    def portal_report_ppd(
        request: Request,
        issuer: dict = Depends(get_portal_issuer),
    ):
        from services.reports.ppd_cobranza import build_ppd_outstanding_report
        report = build_ppd_outstanding_report(issuer["id"])
        return _render_portal(
            request, issuer=issuer,
            template_name="portal_report_ppd.html",
            active_page="reports",
            title="Cobranza PPD",
            extra={"report": report},
        )
