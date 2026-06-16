"""Monthly fiscal report builder."""
import logging

from database import db_rows
from services.sat.cfdi_relacion_labels import compute_net_totals
from services.sat.sat_sync import get_month_totals
from services.ym_helpers import ym_sql_filter

logger = logging.getLogger(__name__)


def build_monthly_report(issuer_id: int, ym: str) -> dict:
    """Build a comprehensive monthly fiscal report.

    Args:
        issuer_id: Tenant ID.
        ym: Year-month in YYYY-MM format.

    Returns:
        Dict with ingresos, gastos_brutos, notas_credito, gastos_neto,
        utilidad_fiscal, iva_neto, cfdi_emitidos, cfdi_recibidos.
    """
    _ym_filt = ym_sql_filter(ym)

    # Issued CFDIs
    emitidos = db_rows(
        f"""SELECT uuid, fecha_emision, rfc_receptor, nombre_receptor, concepto,
                   subtotal, COALESCE(impuestos,0) AS impuestos,
                   COALESCE(retenciones,0) AS retenciones, total, moneda,
                   tipo_comprobante, metodo_pago, status
            FROM sat_cfdi
            WHERE issuer_id = ? AND direction = 'issued'
              AND fecha_emision IS NOT NULL AND {_ym_filt}
            ORDER BY fecha_emision""",
        (issuer_id, ym),
    )

    # Received CFDIs
    recibidos = db_rows(
        f"""SELECT uuid, fecha_emision, rfc_emisor, nombre_emisor, concepto,
                   subtotal, COALESCE(impuestos,0) AS impuestos,
                   COALESCE(retenciones,0) AS retenciones, total, moneda,
                   tipo_comprobante, tipo_relacion, status
            FROM sat_cfdi
            WHERE issuer_id = ? AND direction = 'received'
              AND fecha_emision IS NOT NULL AND {_ym_filt}
            ORDER BY fecha_emision""",
        (issuer_id, ym),
    )

    # Compute issued totals
    issued_totals = get_month_totals(issuer_id, ym, "issued")

    # Compute received net totals using the tipo_relacion-aware function
    vigente_received = [r for r in recibidos if (r.get("status") or "").upper() in ("V", "VIGENTE", "1", "")]
    received_net = compute_net_totals(vigente_received)

    ingresos = {
        "n": len([e for e in emitidos if (e.get("tipo_comprobante") or "").upper() == "I"]),
        "subtotal": issued_totals.get("total_base", 0.0),
        "iva": issued_totals.get("total_iva", 0.0),
        "retenciones": issued_totals.get("total_retenciones", 0.0),
        "total": issued_totals.get("total_base", 0.0) + issued_totals.get("total_iva", 0.0) - issued_totals.get("total_retenciones", 0.0),
    }

    gastos_neto = {
        "n": received_net.get("ingresos_n", 0),
        "subtotal": received_net.get("subtotal", 0.0),
        "iva_acreditable": received_net.get("iva", 0.0),
        "retenciones": received_net.get("retenciones", 0.0),
        "total": received_net.get("total", 0.0),
    }

    notas_credito = {
        "n": received_net.get("notas_n", 0),
        "subtotal": received_net.get("notas_sub", 0.0),
        "iva": received_net.get("notas_iva", 0.0),
        "total": received_net.get("notas_total", 0.0),
    }

    utilidad = ingresos["subtotal"] - gastos_neto["subtotal"]
    iva_neto = ingresos["iva"] - gastos_neto["iva_acreditable"]

    # ISR estimate based on issuer's regimen
    isr_est = _estimate_isr(issuer_id, utilidad)

    return {
        "periodo": ym,
        "ingresos": ingresos,
        "gastos_neto": gastos_neto,
        "notas_credito": notas_credito,
        "utilidad_fiscal": round(utilidad, 2),
        "iva_neto": round(iva_neto, 2),
        "isr_estimado": round(isr_est, 2),
        "cfdi_emitidos": emitidos,
        "cfdi_recibidos": recibidos,
    }


def _estimate_isr(issuer_id: int, utilidad: float) -> float:
    """Rough ISR estimate based on issuer's regimen fiscal."""
    rows = db_rows("SELECT regimen_fiscal FROM issuers WHERE id = ?", (issuer_id,))
    regimen = (rows[0].get("regimen_fiscal") or "601") if rows else "601"

    if regimen == "626":
        # RESICO PF: flat 1-2.5% on ingresos (simplified)
        return max(utilidad * 0.0125, 0)
    elif regimen == "612":
        # PF Actividad Empresarial: approximate with 30% marginal
        return max(utilidad * 0.30, 0)
    else:
        # PM general: 30%
        return max(utilidad * 0.30, 0)
