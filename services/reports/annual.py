"""Annual fiscal report builder."""
import logging

from services.reports.monthly import build_monthly_report

logger = logging.getLogger(__name__)


def build_annual_report(issuer_id: int, year: int) -> dict:
    """Build an annual fiscal report by aggregating 12 monthly reports.

    Args:
        issuer_id: Tenant ID.
        year: Fiscal year (e.g. 2026).

    Returns:
        Dict with months (list of 12 monthly summaries), annual_totals,
        isr_annual_estimate.
    """
    months = []
    totals = {
        "ingresos_subtotal": 0.0,
        "ingresos_iva": 0.0,
        "ingresos_retenciones": 0.0,
        "gastos_subtotal": 0.0,
        "gastos_iva": 0.0,
        "utilidad": 0.0,
        "iva_neto": 0.0,
        "isr_provisionales": 0.0,
    }

    for m in range(1, 13):
        ym = f"{year}-{m:02d}"
        try:
            report = build_monthly_report(issuer_id, ym)
        except Exception as exc:
            logger.warning("Annual report: month %s failed: %s", ym, exc)
            report = _empty_month(ym)

        summary = {
            "ym": ym,
            "ingresos_subtotal": report["ingresos"]["subtotal"],
            "ingresos_iva": report["ingresos"]["iva"],
            "ingresos_retenciones": report["ingresos"]["retenciones"],
            "gastos_subtotal": report["gastos_neto"]["subtotal"],
            "gastos_iva": report["gastos_neto"]["iva_acreditable"],
            "utilidad": report["utilidad_fiscal"],
            "iva_neto": report["iva_neto"],
            "isr_estimado": report["isr_estimado"],
        }
        months.append(summary)

        totals["ingresos_subtotal"] += summary["ingresos_subtotal"]
        totals["ingresos_iva"] += summary["ingresos_iva"]
        totals["ingresos_retenciones"] += summary["ingresos_retenciones"]
        totals["gastos_subtotal"] += summary["gastos_subtotal"]
        totals["gastos_iva"] += summary["gastos_iva"]
        totals["utilidad"] += summary["utilidad"]
        totals["iva_neto"] += summary["iva_neto"]
        totals["isr_provisionales"] += summary["isr_estimado"]

    return {
        "year": year,
        "months": months,
        "totals": {k: round(v, 2) for k, v in totals.items()},
    }


def _empty_month(ym: str) -> dict:
    """Return a zeroed-out monthly report structure."""
    return {
        "periodo": ym,
        "ingresos": {"n": 0, "subtotal": 0, "iva": 0, "retenciones": 0, "total": 0},
        "gastos_neto": {"n": 0, "subtotal": 0, "iva_acreditable": 0, "retenciones": 0, "total": 0},
        "notas_credito": {"n": 0, "subtotal": 0, "iva": 0, "total": 0},
        "utilidad_fiscal": 0,
        "iva_neto": 0,
        "isr_estimado": 0,
        "cfdi_emitidos": [],
        "cfdi_recibidos": [],
    }
