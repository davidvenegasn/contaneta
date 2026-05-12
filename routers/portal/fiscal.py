"""Portal fiscal summary routes."""
import logging

from fastapi import Depends, Query, Request
from fastapi.responses import HTMLResponse

from database import db, db_rows
from routers.deps import get_portal_issuer
from routers.portal._helpers import render_portal, ym_now
from services.fiscal.calculators import (
    IVA_RATE,
    calc_iva,
    calc_pfae_general,
    calc_resico_pf,
)
from services.invoices import foreign_invoices as fi
from services.sat.sat_sync import get_month_totals
from services.ym_helpers import sanitize_ym, shift_ym, ym_to_label

logger = logging.getLogger(__name__)

REGIMEN_OPTIONS = [
    ("RESICO_PF", "RESICO Persona Física"),
    ("PFAE_GENERAL", "Actividad Empresarial y Profesional"),
]


def _get_issuer_regimen(issuer_id: int) -> str:
    """Get issuer fiscal regime from profile, default RESICO_PF."""
    rows = db_rows(
        "SELECT regimen FROM issuer_fiscal_profile WHERE issuer_id = ?",
        (issuer_id,),
    )
    if rows:
        return rows[0].get("regimen") or "RESICO_PF"
    return "RESICO_PF"


def _save_issuer_regimen(issuer_id: int, regimen: str):
    """Save issuer fiscal regime (upsert)."""
    conn = db()
    try:
        conn.execute(
            """
            INSERT INTO issuer_fiscal_profile (issuer_id, regimen, updated_at)
            VALUES (?, ?, datetime('now'))
            ON CONFLICT(issuer_id) DO UPDATE SET regimen = excluded.regimen, updated_at = excluded.updated_at
            """,
            (issuer_id, regimen),
        )
        conn.commit()
    finally:
        conn.close()


def register_fiscal_routes(router, templates):
    """Register Fiscal summary routes on the portal router."""

    def _render_portal(request, **kwargs):
        return render_portal(templates, request, **kwargs)

    @router.get("/fiscal", response_class=HTMLResponse)
    def portal_fiscal(
        request: Request,
        issuer: dict = Depends(get_portal_issuer),
        ym: str | None = Query(None),
        regimen: str | None = Query(None),
    ):
        """Fiscal summary — estimated ISR and IVA for the active month."""
        try:
            issuer_id = issuer["id"]
            if not ym:
                ym = ym_now()
            ym = sanitize_ym(ym, ym_now())

            # Regime: from query param (if changed) or DB
            current_regimen = _get_issuer_regimen(issuer_id)
            if regimen and regimen in dict(REGIMEN_OPTIONS):
                if regimen != current_regimen:
                    _save_issuer_regimen(issuer_id, regimen)
                    current_regimen = regimen

            # Month totals from SAT CFDIs
            issued = get_month_totals(issuer_id, ym, "issued")
            received = get_month_totals(issuer_id, ym, "received")

            ingresos = issued["total_base"]
            gastos_brutos = received["total_base"]
            iva_cobrado = issued["total_iva"]
            iva_pagado_bruto = received["total_iva"]
            isr_retenido = issued.get("total_retenciones", 0.0)
            # For IVA: retenido = retenciones on issued (clients withhold your IVA)
            iva_retenido = issued.get("total_retenciones", 0.0)

            # Deductibility-adjusted totals (LISR Art. 28, LIVA Art. 5-V)
            from services.fiscal.deductibility import compute_deductible_totals
            deduct = compute_deductible_totals(issuer_id, ym)
            gastos = deduct["gastos_deducibles"]
            iva_pagado = deduct["iva_acreditable"]
            deducible_invoices = deduct["detail"]

            # Foreign invoices (gastos extranjeros — always 100% for now)
            fi.ensure_table()
            fi_totals = fi.compute_totals(issuer_id, period_month=ym)
            fi_gastos = fi_totals["sum_gastos"]
            fi_ingresos = fi_totals["sum_ingresos"]

            total_ingresos = ingresos + fi_ingresos
            total_gastos = gastos + fi_gastos

            # ISR estimation
            if current_regimen == "RESICO_PF":
                isr_result = calc_resico_pf(total_ingresos)
            else:
                isr_result = calc_pfae_general(
                    total_ingresos,
                    deducciones_mes=total_gastos,
                    retenciones_isr=isr_retenido,
                )

            # IVA estimation (uses deductibility-adjusted IVA)
            iva_result = calc_iva(
                iva_causado=iva_cobrado,
                iva_acreditable=iva_pagado,
                iva_retenido=iva_retenido,
            )

            utilidad = total_ingresos - total_gastos

            return _render_portal(
                request,
                issuer=issuer,
                template_name="portal_fiscal.html",
                active_page="fiscal",
                title="Resumen Fiscal",
                extra={
                    "ym": ym,
                    "ym_label": ym_to_label(ym),
                    "prev_ym": shift_ym(ym, -1),
                    "next_ym": shift_ym(ym, 1),
                    "current_regimen": current_regimen,
                    "regimen_options": REGIMEN_OPTIONS,
                    "total_ingresos": round(total_ingresos, 2),
                    "total_gastos": round(total_gastos, 2),
                    "utilidad": round(utilidad, 2),
                    "gastos_brutos": round(gastos_brutos, 2),
                    "fi_gastos": round(fi_gastos, 2),
                    "fi_ingresos": round(fi_ingresos, 2),
                    "deducible_invoices": deducible_invoices,
                    "total_deducible": round(gastos, 2),
                    "iva_cobrado": round(iva_cobrado, 2),
                    "iva_pagado": round(iva_pagado, 2),
                    "iva_retenido": round(iva_retenido, 2),
                    "isr_retenido": round(isr_retenido, 2),
                    "isr": isr_result,
                    "iva": iva_result,
                },
            )
        except Exception:
            logger.exception("portal: error renderizando /portal/fiscal")
            raise
