"""Fiscal calculators for Mexican tax regimes (ISR, IVA).

IMPORTANT: These are ESTIMATES based on officially published SAT 2026 rates.
They do NOT replace a formal tax return or professional accounting advice.

Sources:
- RESICO PF: Art. 113-E LISR, Anexo 8 RMF 2026
- PFAE General: Art. 96 LISR, Tarifa mensual pagos provisionales 2026
- IVA: Art. 1 LIVA (16%)
"""

from datetime import date

DISCLAIMER = (
    "Estimación con base en tasas SAT 2026 vigentes a {fecha}. "
    "NO sustituye declaración formal ni asesoría contable."
)

# ── RESICO PF — Art. 113-E LISR (tasas sobre ingreso bruto, sin deducciones) ──
# Publicadas en Anexo 8 RMF 2026, DOF 28/12/2025
RESICO_PF_BRACKETS_2026 = [
    (25_000.00, 0.0100),
    (50_000.00, 0.0110),
    (83_333.33, 0.0150),
    (208_333.33, 0.0200),
    (3_500_000.00, 0.0250),
]

# ── PFAE General — Art. 96 LISR (tarifa mensual pagos provisionales 2026) ──
# Publicada en Anexo 8 RMF 2026, DOF 28/12/2025
PFAE_TARIFA_MENSUAL_2026 = [
    # (limite_inferior, limite_superior, cuota_fija, tasa_excedente)
    (0.01, 746.04, 0.00, 0.0192),
    (746.05, 6_332.05, 14.32, 0.0640),
    (6_332.06, 11_128.01, 371.83, 0.1088),
    (11_128.02, 12_935.82, 893.63, 0.1600),
    (12_935.83, 15_487.71, 1_182.88, 0.1792),
    (15_487.72, 31_236.49, 1_639.32, 0.2136),
    (31_236.50, 49_233.00, 4_005.46, 0.2352),
    (49_233.01, 93_993.90, 8_237.45, 0.3000),
    (93_993.91, 125_325.20, 21_665.72, 0.3200),
    (125_325.21, 375_975.61, 31_691.85, 0.3400),
    (375_975.62, float("inf"), 116_912.87, 0.3500),
]

IVA_RATE = 0.16  # Art. 1 LIVA


def calc_resico_pf(ingresos_mes: float) -> dict:
    """Calculate ISR for RESICO PF (Régimen Simplificado de Confianza).

    RESICO applies a flat rate on total monthly income (no deductions).
    Rate depends on the income bracket.

    Args:
        ingresos_mes: Total invoiced income for the month (MXN, before IVA).

    Returns:
        dict with isr_estimado, tasa_aplicada, base_gravable, disclaimer.
    """
    if ingresos_mes <= 0:
        return {
            "isr_estimado": 0.0,
            "tasa_aplicada": 0.0,
            "base_gravable": 0.0,
            "disclaimer": DISCLAIMER.format(fecha=date.today().isoformat()),
        }

    tasa = RESICO_PF_BRACKETS_2026[-1][1]  # default: max bracket
    for limit, rate in RESICO_PF_BRACKETS_2026:
        if ingresos_mes <= limit:
            tasa = rate
            break

    isr = round(ingresos_mes * tasa, 2)
    return {
        "isr_estimado": isr,
        "tasa_aplicada": tasa,
        "base_gravable": ingresos_mes,
        "disclaimer": DISCLAIMER.format(fecha=date.today().isoformat()),
    }


def calc_pfae_general(
    ingresos_mes: float,
    deducciones_mes: float = 0.0,
    retenciones_isr: float = 0.0,
) -> dict:
    """Calculate provisional ISR for PFAE General (Art. 96 LISR).

    Applies progressive tariff to taxable base (ingresos - deducciones).

    Args:
        ingresos_mes: Total income for the month (MXN).
        deducciones_mes: Total deductible expenses for the month (MXN).
        retenciones_isr: ISR already withheld by clients (MXN).

    Returns:
        dict with isr_provisional, base_gravable, cuota_fija,
        tasa_marginal, isr_antes_retenciones, disclaimer.
    """
    base = max(0.0, ingresos_mes - deducciones_mes)

    if base <= 0:
        return {
            "isr_provisional": 0.0,
            "base_gravable": 0.0,
            "cuota_fija": 0.0,
            "tasa_marginal": 0.0,
            "isr_antes_retenciones": 0.0,
            "disclaimer": DISCLAIMER.format(fecha=date.today().isoformat()),
        }

    # Find applicable bracket
    cuota_fija = 0.0
    tasa = 0.0
    limite_inferior = 0.01
    for li, ls, cf, t in PFAE_TARIFA_MENSUAL_2026:
        if base <= ls:
            cuota_fija = cf
            tasa = t
            limite_inferior = li
            break

    excedente = max(0.0, base - limite_inferior)
    isr_bruto = round(cuota_fija + (excedente * tasa), 2)
    isr_provisional = round(max(0.0, isr_bruto - retenciones_isr), 2)

    return {
        "isr_provisional": isr_provisional,
        "base_gravable": round(base, 2),
        "cuota_fija": cuota_fija,
        "tasa_marginal": tasa,
        "isr_antes_retenciones": isr_bruto,
        "disclaimer": DISCLAIMER.format(fecha=date.today().isoformat()),
    }


def calc_iva(
    iva_causado: float,
    iva_acreditable: float,
    iva_retenido: float = 0.0,
) -> dict:
    """Calculate net IVA to pay or in favor.

    IVA neto = causado - acreditable - retenido
    Positive = to pay; Negative = saldo a favor.

    Args:
        iva_causado: IVA charged on sales (16% of income subtotal).
        iva_acreditable: IVA paid on deductible purchases.
        iva_retenido: IVA withheld by clients.

    Returns:
        dict with iva_a_pagar, iva_causado, iva_acreditable,
        iva_retenido, saldo_a_favor, disclaimer.
    """
    neto = round(iva_causado - iva_acreditable - iva_retenido, 2)
    return {
        "iva_a_pagar": max(0.0, neto),
        "saldo_a_favor": abs(min(0.0, neto)),
        "iva_causado": round(iva_causado, 2),
        "iva_acreditable": round(iva_acreditable, 2),
        "iva_retenido": round(iva_retenido, 2),
        "disclaimer": DISCLAIMER.format(fecha=date.today().isoformat()),
    }
