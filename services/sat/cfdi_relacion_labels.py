"""Human-readable labels and accounting semantics for CFDI TipoRelacion."""

# c_TipoRelacion catalog (SAT)
TIPO_RELACION_LABELS = {
    "01": "Nota de crédito",
    "02": "Nota de débito",
    "03": "Devolución",
    "04": "Sustitución",
    "05": "Traslado",
    "06": "Traslado previo",
    "07": "Anticipo aplicado",
    "08": "Operación CFDI Régimen 23",
    "09": "Factura por traslados",
}

# Which TipoRelacion subtracts from monthly net (gasto deducible)
# 01/03 = real reduction (refund); 07 = already deducted in prior month (anticipo)
SUBTRACTS_FROM_TOTAL = {"01", "03", "07"}

# Which is informational only (no impact on totals)
NEUTRAL = {"04", "05", "06"}

# Badge color mapping for UI
BADGE_COLORS = {
    "I": "info",
    "N": "neutral",
    "P": "accent",
    "T": "neutral",
}

EGRESO_BADGE_COLORS = {
    "01": "warn",
    "03": "warn",
    "04": "neutral",
    "07": "ppd",
}


def label_for_received(tipo_comprobante: str, tipo_relacion: str | None) -> str:
    """Return the human label for a received CFDI row in the UI."""
    tc = (tipo_comprobante or "").upper()
    if tc == "I":
        return "Ingreso"
    if tc == "N":
        return "Nómina"
    if tc == "P":
        return "Pago (REP)"
    if tc == "T":
        return "Traslado"
    if tc == "E":
        return TIPO_RELACION_LABELS.get(tipo_relacion or "", "Egreso")
    return tipo_comprobante or "—"


def badge_color(tipo_comprobante: str, tipo_relacion: str | None) -> str:
    """Return the CSS badge variant for a CFDI row."""
    tc = (tipo_comprobante or "").upper()
    if tc == "E":
        return EGRESO_BADGE_COLORS.get(tipo_relacion or "", "warn")
    return BADGE_COLORS.get(tc, "neutral")


def signed_amount(total: float, tipo_comprobante: str, tipo_relacion: str | None) -> float:
    """Return total with the sign that should be applied to monthly net.

    Positive = sums to gastos del mes.
    Negative = subtracts from gastos del mes (NC reales, anticipos aplicados).
    Zero = neutral (sustitución, traslados, pagos).
    """
    tc = (tipo_comprobante or "").upper()
    tr = tipo_relacion or ""
    if tc == "P":  # pagos no afectan
        return 0.0
    if tc == "E":
        if tr in SUBTRACTS_FROM_TOTAL:
            return -abs(total)
        if tr in NEUTRAL:
            return 0.0
        # Default: unknown E type → treat as NC (conservative)
        return -abs(total)
    return abs(total)  # I, N suman


def signed_multiplier(tipo_comprobante: str, tipo_relacion: str | None) -> int:
    """Return +1 / -1 / 0 to apply to ALL fiscal fields of the CFDI.

    Use this to compute net subtotal, net IVA, net retenciones, net total
    consistently — same sign for every field of the row.
    """
    tc = (tipo_comprobante or "").upper()
    tr = tipo_relacion or ""
    if tc == "P":
        return 0
    if tc == "E":
        if tr in SUBTRACTS_FROM_TOTAL:
            return -1
        if tr in NEUTRAL:
            return 0
        return -1  # conservative default
    return 1  # I, N, T


def compute_net_totals(rows: list) -> dict:
    """Aggregate received CFDI into net subtotal, IVA, retenciones, total.

    Each row should expose: tipo_comprobante, tipo_relacion, subtotal, impuestos
    (IVA trasladado), retenciones, total. IVA from notas/anticipos is subtracted
    from IVA acreditable so the user sees the real deductible amounts that
    match SAT's prellenado.
    """
    net = {
        "subtotal": 0.0, "iva": 0.0, "retenciones": 0.0, "total": 0.0,
        # Breakdown for the resumen card
        "ingresos_n": 0, "ingresos_sub": 0.0, "ingresos_iva": 0.0, "ingresos_total": 0.0,
        "notas_n": 0, "notas_sub": 0.0, "notas_iva": 0.0, "notas_total": 0.0,
        "anticipos_n": 0, "anticipos_sub": 0.0, "anticipos_iva": 0.0, "anticipos_total": 0.0,
    }
    for r in rows:
        tc = (r.get("tipo_comprobante") or "").upper()
        tr = r.get("tipo_relacion") or ""
        m = signed_multiplier(tc, tr)
        if m == 0:
            continue
        sub = float(r.get("subtotal") or 0)
        iva = float(r.get("impuestos") or 0)
        ret = float(r.get("retenciones") or 0)
        tot = float(r.get("total") or 0)

        net["subtotal"] += m * sub
        net["iva"] += m * iva
        net["retenciones"] += m * ret
        net["total"] += m * tot

        # Bucket per tipo for the card breakdown
        if tc == "I":
            net["ingresos_n"] += 1
            net["ingresos_sub"] += sub
            net["ingresos_iva"] += iva
            net["ingresos_total"] += tot
        elif tc == "E" and tr in ("01", "03"):
            net["notas_n"] += 1
            net["notas_sub"] += sub
            net["notas_iva"] += iva
            net["notas_total"] += tot
        elif tc == "E" and tr == "07":
            net["anticipos_n"] += 1
            net["anticipos_sub"] += sub
            net["anticipos_iva"] += iva
            net["anticipos_total"] += tot
    return net
