"""Financial statements — Income Statement and Balance Sheet.

Provides month-level income statement (Estado de Resultados) with YTD,
and a basic balance sheet (Balance General) using CFDI totals and the
existing fiscal calculators.

IMPORTANT: These are ESTIMATES. They do NOT replace formal financial
statements prepared by a certified accountant.
"""

import logging
from datetime import date

from database import db_rows
from services.fiscal.calculators import DISCLAIMER, calc_iva, calc_pfae_general, calc_resico_pf
from services.fiscal.deductibility import compute_deductible_totals
from services.sat.sat_sync import get_month_totals

logger = logging.getLogger(__name__)


def _get_issuer_regimen(issuer_id: int) -> str:
    """Get issuer fiscal regime from profile, default RESICO_PF."""
    rows = db_rows(
        "SELECT regimen FROM issuer_fiscal_profile WHERE issuer_id = ?",
        (issuer_id,),
    )
    if rows:
        return rows[0].get("regimen") or "RESICO_PF"
    return "RESICO_PF"


def _months_range(ym: str) -> list[str]:
    """Return list of YYYY-MM from YYYY-01 through the given YYYY-MM (inclusive)."""
    parts = ym.split("-")
    year = int(parts[0])
    month = int(parts[1])
    return [f"{year:04d}-{m:02d}" for m in range(1, month + 1)]


def _income_totals_ytd(issuer_id: int, ym: str) -> dict:
    """Issued CFDI totals from January to the given month (YTD)."""
    year = ym[:4]
    rows = db_rows(
        """
        SELECT
            COALESCE(SUM(COALESCE(subtotal, total, 0)), 0) AS total_base,
            COALESCE(SUM(COALESCE(impuestos, 0)), 0)       AS total_iva,
            COALESCE(SUM(COALESCE(retenciones, 0)), 0)     AS total_retenciones
        FROM sat_cfdi
        WHERE issuer_id = ?
          AND direction = 'issued'
          AND fecha_emision IS NOT NULL
          AND substr(fecha_emision, 1, 4) = ?
          AND substr(fecha_emision, 1, 7) <= ?
          AND (total IS NULL OR total >= 0.01)
        """,
        (issuer_id, year, ym),
    )
    if not rows:
        return {"total_base": 0.0, "total_iva": 0.0, "total_retenciones": 0.0}
    r = rows[0]
    return {
        "total_base": float(r.get("total_base") or 0),
        "total_iva": float(r.get("total_iva") or 0),
        "total_retenciones": float(r.get("total_retenciones") or 0),
    }


def _expense_totals_ytd(issuer_id: int, ym: str) -> dict:
    """Received CFDI totals (expenses) from January to the given month (YTD)."""
    year = ym[:4]
    rows = db_rows(
        """
        SELECT
            COALESCE(SUM(COALESCE(subtotal, total, 0)), 0) AS total_base,
            COALESCE(SUM(COALESCE(impuestos, 0)), 0)       AS total_iva
        FROM sat_cfdi
        WHERE issuer_id = ?
          AND direction = 'received'
          AND fecha_emision IS NOT NULL
          AND substr(fecha_emision, 1, 4) = ?
          AND substr(fecha_emision, 1, 7) <= ?
          AND total IS NOT NULL AND total >= 0.01
          AND (tipo_comprobante IS NULL OR UPPER(TRIM(tipo_comprobante)) != 'N')
        """,
        (issuer_id, year, ym),
    )
    if not rows:
        return {"total_base": 0.0, "total_iva": 0.0}
    r = rows[0]
    return {
        "total_base": float(r.get("total_base") or 0),
        "total_iva": float(r.get("total_iva") or 0),
    }


def _uncollected_issued(issuer_id: int, ym: str) -> float:
    """Issued CFDIs with metodo_pago PPD up to the month (accounts receivable proxy)."""
    rows = db_rows(
        """
        SELECT COALESCE(SUM(COALESCE(total, 0)), 0) AS v
        FROM sat_cfdi
        WHERE issuer_id = ?
          AND direction = 'issued'
          AND fecha_emision IS NOT NULL
          AND substr(fecha_emision, 1, 7) <= ?
          AND (total IS NULL OR total >= 0.01)
          AND UPPER(TRIM(COALESCE(metodo_pago, ''))) = 'PPD'
        """,
        (issuer_id, ym),
    )
    return float(rows[0]["v"]) if rows else 0.0


def _unpaid_received(issuer_id: int, ym: str) -> float:
    """Received CFDIs with metodo_pago PPD up to the month (accounts payable proxy)."""
    rows = db_rows(
        """
        SELECT COALESCE(SUM(COALESCE(total, 0)), 0) AS v
        FROM sat_cfdi
        WHERE issuer_id = ?
          AND direction = 'received'
          AND fecha_emision IS NOT NULL
          AND substr(fecha_emision, 1, 7) <= ?
          AND total IS NOT NULL AND total >= 0.01
          AND (tipo_comprobante IS NULL OR UPPER(TRIM(tipo_comprobante)) != 'N')
          AND UPPER(TRIM(COALESCE(metodo_pago, ''))) = 'PPD'
        """,
        (issuer_id, ym),
    )
    return float(rows[0]["v"]) if rows else 0.0


def income_statement(issuer_id: int, ym: str) -> dict:
    """Estado de Resultados for a single month with YTD comparison.

    Returns a dict with keys: ym, month, ytd, regimen, disclaimer.
    Both month and ytd contain: ingresos, gastos, utilidad_bruta,
    isr_estimado, iva_cobrado, iva_pagado, iva_neto, utilidad_neta.
    """
    # Monthly totals
    issued_m = get_month_totals(issuer_id, ym, "issued")
    received_m = get_month_totals(issuer_id, ym, "received")

    # Deductibility-adjusted expenses for the month
    deduct_m = compute_deductible_totals(issuer_id, ym)

    ingresos_m = issued_m["total_base"]
    gastos_m = deduct_m.get("gastos_deducibles", received_m["total_base"])
    utilidad_bruta_m = round(ingresos_m - gastos_m, 2)
    iva_cobrado_m = issued_m["total_iva"]
    iva_pagado_m = deduct_m.get("iva_acreditable", received_m["total_iva"])
    retenciones_m = issued_m.get("total_retenciones", 0.0)

    regimen = _get_issuer_regimen(issuer_id)
    if regimen == "RESICO_PF":
        isr_m = calc_resico_pf(ingresos_m)["isr_estimado"]
    else:
        isr_m = calc_pfae_general(ingresos_m, gastos_m, retenciones_m)["isr_provisional"]

    iva_result_m = calc_iva(iva_cobrado_m, iva_pagado_m, retenciones_m)
    iva_neto_m = round(iva_result_m["iva_a_pagar"] - iva_result_m["saldo_a_favor"], 2)
    utilidad_neta_m = round(utilidad_bruta_m - isr_m, 2)

    # YTD totals
    inc_ytd = _income_totals_ytd(issuer_id, ym)
    exp_ytd = _expense_totals_ytd(issuer_id, ym)

    ingresos_ytd = inc_ytd["total_base"]
    gastos_ytd = exp_ytd["total_base"]
    utilidad_bruta_ytd = round(ingresos_ytd - gastos_ytd, 2)
    iva_cobrado_ytd = inc_ytd["total_iva"]
    iva_pagado_ytd = exp_ytd["total_iva"]
    retenciones_ytd = inc_ytd.get("total_retenciones", 0.0)

    if regimen == "RESICO_PF":
        isr_ytd = calc_resico_pf(ingresos_ytd)["isr_estimado"]
    else:
        isr_ytd = calc_pfae_general(ingresos_ytd, gastos_ytd, retenciones_ytd)["isr_provisional"]

    iva_result_ytd = calc_iva(iva_cobrado_ytd, iva_pagado_ytd, retenciones_ytd)
    iva_neto_ytd = round(iva_result_ytd["iva_a_pagar"] - iva_result_ytd["saldo_a_favor"], 2)
    utilidad_neta_ytd = round(utilidad_bruta_ytd - isr_ytd, 2)

    def _build(ingresos, gastos, ub, isr, iva_c, iva_p, iva_n, un):
        return {
            "ingresos": round(ingresos, 2),
            "gastos": round(gastos, 2),
            "utilidad_bruta": round(ub, 2),
            "isr_estimado": round(isr, 2),
            "iva_cobrado": round(iva_c, 2),
            "iva_pagado": round(iva_p, 2),
            "iva_neto": round(iva_n, 2),
            "utilidad_neta": round(un, 2),
        }

    return {
        "ym": ym,
        "month": _build(ingresos_m, gastos_m, utilidad_bruta_m, isr_m,
                         iva_cobrado_m, iva_pagado_m, iva_neto_m, utilidad_neta_m),
        "ytd": _build(ingresos_ytd, gastos_ytd, utilidad_bruta_ytd, isr_ytd,
                       iva_cobrado_ytd, iva_pagado_ytd, iva_neto_ytd, utilidad_neta_ytd),
        # Backward-compat flat keys (used by older template)
        "ingresos": round(ingresos_m, 2),
        "gastos": round(gastos_m, 2),
        "utilidad_bruta": round(utilidad_bruta_m, 2),
        "isr_estimado": round(isr_m, 2),
        "utilidad_neta": round(utilidad_neta_m, 2),
        "regimen": regimen,
        "disclaimer": DISCLAIMER.format(fecha=date.today().isoformat()),
    }


def balance_summary(issuer_id: int, ym: str) -> dict:
    """Balance General — assets, liabilities, and equity as of end of month.

    Assets:
        - Cuentas por cobrar (issued CFDIs with PPD = payment pending)
        - Saldo estimado en banco (YTD income - YTD expenses, floored at 0)

    Liabilities:
        - Cuentas por pagar (received CFDIs with PPD)
        - Impuestos por pagar (estimated ISR + net IVA)

    Equity:
        - Utilidad acumulada (assets - liabilities)
    """
    # Assets
    cxc = _uncollected_issued(issuer_id, ym)
    inc_ytd = _income_totals_ytd(issuer_id, ym)
    exp_ytd = _expense_totals_ytd(issuer_id, ym)
    saldo_banco = max(0.0, round(inc_ytd["total_base"] - exp_ytd["total_base"], 2))
    total_assets = round(cxc + saldo_banco, 2)

    # Liabilities
    cxp = _unpaid_received(issuer_id, ym)
    regimen = _get_issuer_regimen(issuer_id)
    if regimen == "RESICO_PF":
        isr_est = calc_resico_pf(inc_ytd["total_base"])["isr_estimado"]
    else:
        isr_est = calc_pfae_general(
            inc_ytd["total_base"], exp_ytd["total_base"], inc_ytd.get("total_retenciones", 0.0)
        )["isr_provisional"]
    iva_result = calc_iva(
        inc_ytd["total_iva"], exp_ytd["total_iva"], inc_ytd.get("total_retenciones", 0.0)
    )
    impuestos = round(max(0.0, isr_est) + iva_result["iva_a_pagar"], 2)
    total_liabilities = round(cxp + impuestos, 2)

    # Equity = Assets - Liabilities
    equity = round(total_assets - total_liabilities, 2)

    # Backward-compat: compute accumulated totals for old template
    months = _months_range(ym)

    return {
        "ym": ym,
        "assets": {
            "cuentas_por_cobrar": cxc,
            "saldo_estimado_banco": saldo_banco,
            "total": total_assets,
        },
        "liabilities": {
            "cuentas_por_pagar": cxp,
            "impuestos_por_pagar": impuestos,
            "total": total_liabilities,
        },
        "equity": {
            "utilidad_acumulada": equity,
            "total": equity,
        },
        "balanced": abs(total_assets - (total_liabilities + equity)) < 0.01,
        # Backward-compat flat keys
        "meses_incluidos": len(months),
        "ingresos_acumulados": round(inc_ytd["total_base"], 2),
        "gastos_acumulados": round(exp_ytd["total_base"], 2),
        "posicion_neta": round(inc_ytd["total_base"] - exp_ytd["total_base"], 2),
        "disclaimer": DISCLAIMER.format(fecha=date.today().isoformat()),
    }
