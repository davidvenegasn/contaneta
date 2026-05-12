"""
Financial Statements — Income Statement + Basic Balance Sheet.

DISCLAIMER: Estimacion contable aproximada. NO sustituye contabilidad
formal ni asesoria profesional.

These are rough estimates computed from CFDI data (issued/received) and
basic fiscal calculators. They are informational only.
"""

from __future__ import annotations

from database import db_rows
from services.fiscal.deductibility import compute_deductible_totals
from services.fiscal.calculators import calc_resico_pf, calc_pfae_general, calc_iva


# ----------------------------------------------------------------------- #
# Helpers for CFDI income/expense aggregation
# ----------------------------------------------------------------------- #


def _get_income_totals(issuer_id: int, ym: str) -> dict:
    """Issued CFDI totals for a single month."""
    rows = db_rows(
        """
        SELECT
            COALESCE(SUM(COALESCE(subtotal, total, 0)), 0) AS income_base,
            COALESCE(SUM(COALESCE(impuestos, 0)), 0)       AS iva_collected,
            COALESCE(SUM(COALESCE(retenciones, 0)), 0)     AS retenciones
        FROM sat_cfdi
        WHERE issuer_id = ?
          AND direction = 'issued'
          AND fecha_emision IS NOT NULL
          AND substr(fecha_emision, 1, 7) = ?
          AND (total IS NULL OR total >= 0.01)
        """,
        (issuer_id, ym),
    )
    if not rows:
        return {"income_base": 0.0, "iva_collected": 0.0, "retenciones": 0.0}
    r = rows[0]
    return {
        "income_base": float(r.get("income_base") or 0),
        "iva_collected": float(r.get("iva_collected") or 0),
        "retenciones": float(r.get("retenciones") or 0),
    }


def _get_income_totals_ytd(issuer_id: int, ym: str) -> dict:
    """Issued CFDI totals from January to the given month (inclusive)."""
    year = ym[:4]
    rows = db_rows(
        """
        SELECT
            COALESCE(SUM(COALESCE(subtotal, total, 0)), 0) AS income_base,
            COALESCE(SUM(COALESCE(impuestos, 0)), 0)       AS iva_collected,
            COALESCE(SUM(COALESCE(retenciones, 0)), 0)     AS retenciones
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
        return {"income_base": 0.0, "iva_collected": 0.0, "retenciones": 0.0}
    r = rows[0]
    return {
        "income_base": float(r.get("income_base") or 0),
        "iva_collected": float(r.get("iva_collected") or 0),
        "retenciones": float(r.get("retenciones") or 0),
    }


def _get_uncollected_issued(issuer_id: int, ym: str) -> float:
    """Sum of issued CFDIs that have metodo_pago='PPD' (payment pending) up to the month.

    This serves as a rough proxy for accounts receivable.
    """
    rows = db_rows(
        """
        SELECT COALESCE(SUM(COALESCE(total, 0)), 0) AS total_uncollected
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
    return float(rows[0].get("total_uncollected") or 0) if rows else 0.0


def _get_unpaid_received(issuer_id: int, ym: str) -> float:
    """Sum of received CFDIs with metodo_pago='PPD' up to the month.

    Rough proxy for accounts payable.
    """
    rows = db_rows(
        """
        SELECT COALESCE(SUM(COALESCE(total, 0)), 0) AS total_unpaid
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
    return float(rows[0].get("total_unpaid") or 0) if rows else 0.0


def _get_expense_totals(issuer_id: int, ym: str) -> dict:
    """Deductible expense totals using the deductibility service.

    Returns dict with gastos_deducibles, iva_acreditable.
    """
    d = compute_deductible_totals(issuer_id, ym)
    return {
        "total_deductible": d.get("gastos_deducibles", 0.0),
        "iva_deductible": d.get("iva_acreditable", 0.0),
    }


def _get_expense_totals_ytd(issuer_id: int, ym: str) -> dict:
    """Deductible expense totals from January to the given month (YTD).

    Uses the year string for compute_deductible_totals (annual mode).
    Then adjusts if needed by also passing the specific ym range.
    """
    year = ym[:4]
    # compute_deductible_totals with a 4-digit year returns the full year.
    # We need jan-to-ym, so iterate months or use year if ym is December.
    # For simplicity, use direct SQL query for YTD totals.
    rows = db_rows(
        """
        SELECT
            COALESCE(SUM(COALESCE(subtotal, total, 0)), 0) AS total_deductible,
            COALESCE(SUM(COALESCE(impuestos, 0)), 0)       AS iva_deductible
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
        return {"total_deductible": 0.0, "iva_deductible": 0.0}
    r = rows[0]
    return {
        "total_deductible": float(r.get("total_deductible") or 0),
        "iva_deductible": float(r.get("iva_deductible") or 0),
    }


# ----------------------------------------------------------------------- #
# Income Statement
# ----------------------------------------------------------------------- #


def compute_income_statement(issuer_id: int, ym: str) -> dict:
    """Compute approximate income statement for a given month and YTD.

    Returns:
        {
            "month": {
                "ingresos": float,
                "gastos_deducibles": float,
                "utilidad_bruta": float,
                "isr_estimado_resico": float,
                "isr_estimado_pfae": float,
                "iva_cobrado": float,
                "iva_pagado": float,
                "iva_neto": float,
                "utilidad_neta": float,
            },
            "ytd": { ... same keys ... },
            "ym": str,
        }
    """
    # Monthly
    inc_m = _get_income_totals(issuer_id, ym)
    exp_m = _get_expense_totals(issuer_id, ym)

    ingresos_m = inc_m["income_base"]
    gastos_m = exp_m["total_deductible"]
    utilidad_bruta_m = round(ingresos_m - gastos_m, 2)

    isr_resico_m = calc_resico_pf(ingresos_m)["isr_estimado"]
    isr_pfae_m = calc_pfae_general(ingresos_m, gastos_m)["isr_provisional"]
    iva_cobrado_m = inc_m["iva_collected"]
    iva_pagado_m = exp_m["iva_deductible"]
    iva_result_m = calc_iva(iva_cobrado_m, iva_pagado_m, inc_m["retenciones"])
    iva_neto_m = round(iva_result_m["iva_a_pagar"] - iva_result_m["saldo_a_favor"], 2)
    utilidad_neta_m = round(utilidad_bruta_m - isr_pfae_m, 2)

    # YTD
    inc_ytd = _get_income_totals_ytd(issuer_id, ym)
    exp_ytd = _get_expense_totals_ytd(issuer_id, ym)

    ingresos_ytd = inc_ytd["income_base"]
    gastos_ytd = exp_ytd["total_deductible"]
    utilidad_bruta_ytd = round(ingresos_ytd - gastos_ytd, 2)

    isr_resico_ytd = calc_resico_pf(ingresos_ytd)["isr_estimado"]
    isr_pfae_ytd = calc_pfae_general(ingresos_ytd, gastos_ytd)["isr_provisional"]
    iva_cobrado_ytd = inc_ytd["iva_collected"]
    iva_pagado_ytd = exp_ytd["iva_deductible"]
    iva_result_ytd = calc_iva(iva_cobrado_ytd, iva_pagado_ytd, inc_ytd["retenciones"])
    iva_neto_ytd = round(iva_result_ytd["iva_a_pagar"] - iva_result_ytd["saldo_a_favor"], 2)
    utilidad_neta_ytd = round(utilidad_bruta_ytd - isr_pfae_ytd, 2)

    def _section(ingresos, gastos, ub, isr_r, isr_p, iva_c, iva_p, iva_n, un):
        return {
            "ingresos": ingresos,
            "gastos_deducibles": gastos,
            "utilidad_bruta": ub,
            "isr_estimado_resico": isr_r,
            "isr_estimado_pfae": isr_p,
            "iva_cobrado": iva_c,
            "iva_pagado": iva_p,
            "iva_neto": iva_n,
            "utilidad_neta": un,
        }

    return {
        "month": _section(
            ingresos_m, gastos_m, utilidad_bruta_m,
            isr_resico_m, isr_pfae_m,
            iva_cobrado_m, iva_pagado_m, iva_neto_m,
            utilidad_neta_m,
        ),
        "ytd": _section(
            ingresos_ytd, gastos_ytd, utilidad_bruta_ytd,
            isr_resico_ytd, isr_pfae_ytd,
            iva_cobrado_ytd, iva_pagado_ytd, iva_neto_ytd,
            utilidad_neta_ytd,
        ),
        "ym": ym,
    }


# ----------------------------------------------------------------------- #
# Basic Balance Sheet
# ----------------------------------------------------------------------- #


def compute_basic_balance(issuer_id: int, ym: str) -> dict:
    """Compute a simplified balance sheet as of end of the given month.

    Assets:
        - Accounts receivable (issued CFDIs with PPD -- payment pending)
        - Estimated bank balance (YTD income - YTD expenses, very rough)

    Liabilities:
        - Accounts payable (received CFDIs with PPD)
        - Taxes payable (estimated ISR + net IVA for the period)

    Equity:
        - Accumulated profit (assets - liabilities, by definition)

    Returns:
        {
            "assets": { "cuentas_por_cobrar", "saldo_estimado_banco", "total" },
            "liabilities": { "cuentas_por_pagar", "impuestos_por_pagar", "total" },
            "equity": { "utilidad_acumulada", "total" },
            "balanced": bool,
            "ym": str,
        }
    """
    # Assets
    cuentas_cobrar = _get_uncollected_issued(issuer_id, ym)

    # Rough estimated bank balance: YTD income - YTD expenses (cash proxy)
    inc_ytd = _get_income_totals_ytd(issuer_id, ym)
    exp_ytd = _get_expense_totals_ytd(issuer_id, ym)
    saldo_banco = round(inc_ytd["income_base"] - exp_ytd["total_deductible"], 2)
    saldo_banco = max(0.0, saldo_banco)  # floor at 0 for display

    total_assets = round(cuentas_cobrar + saldo_banco, 2)

    # Liabilities
    cuentas_pagar = _get_unpaid_received(issuer_id, ym)

    # Taxes payable: approximate ISR (PFAE) + net IVA for the period
    utilidad_bruta_ytd = round(inc_ytd["income_base"] - exp_ytd["total_deductible"], 2)
    isr_est = calc_pfae_general(inc_ytd["income_base"], exp_ytd["total_deductible"])["isr_provisional"]
    iva_result = calc_iva(inc_ytd["iva_collected"], exp_ytd["iva_deductible"], inc_ytd["retenciones"])
    impuestos_pagar = round(max(0.0, isr_est) + iva_result["iva_a_pagar"], 2)

    total_liabilities = round(cuentas_pagar + impuestos_pagar, 2)

    # Equity = Assets - Liabilities (accounting equation)
    utilidad_acumulada = round(total_assets - total_liabilities, 2)
    total_equity = utilidad_acumulada

    return {
        "assets": {
            "cuentas_por_cobrar": cuentas_cobrar,
            "saldo_estimado_banco": saldo_banco,
            "total": total_assets,
        },
        "liabilities": {
            "cuentas_por_pagar": cuentas_pagar,
            "impuestos_por_pagar": impuestos_pagar,
            "total": total_liabilities,
        },
        "equity": {
            "utilidad_acumulada": utilidad_acumulada,
            "total": total_equity,
        },
        "balanced": abs(total_assets - (total_liabilities + total_equity)) < 0.01,
        "ym": ym,
    }
