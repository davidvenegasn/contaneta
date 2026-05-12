# Fiscal Summary Page Guide

**Route:** `/portal/fiscal`
**Status:** DRAFT — requires accountant review before production use

## Overview

The Fiscal Summary page provides monthly ISR and IVA estimates based on the issuer's CFDI data and selected tax regime. It is NOT a substitute for a formal tax return.

## Supported Regimes

| Regime | Method | Art. |
|--------|--------|------|
| RESICO PF | Flat rate on gross income (1.00–2.50%) | Art. 113-E LISR |
| PFAE General | Progressive tariff (cuota fija + tasa sobre excedente) | Art. 96 LISR |

Regime is persisted per issuer in `issuer_fiscal_profile` table and can be changed via the dropdown selector on the page.

## Data Sources

| Metric | Source |
|--------|--------|
| Ingresos (income) | `sat_cfdi` issued + `foreign_invoices` INGRESO |
| Gastos (expenses) | `sat_cfdi` received + `foreign_invoices` GASTO |
| IVA cobrado | `sat_cfdi` issued → `impuestos` column |
| IVA pagado | `sat_cfdi` received → `impuestos` column |
| ISR retenido | `sat_cfdi` issued → `retenciones` column |

## ISR Calculation

### RESICO PF
```
ISR = ingresos_brutos × tasa_bracket
```
No deductions allowed. Rate depends on monthly income bracket (see `calculators.py`).

### PFAE General
```
base = ingresos - deducciones
excedente = base - limite_inferior
ISR_bruto = cuota_fija + (excedente × tasa)
ISR_provisional = ISR_bruto - retenciones_isr
```

## IVA Calculation
```
IVA_neto = causado - acreditable - retenido
Positive → IVA a pagar
Negative → Saldo a favor
```

## Files

| File | Purpose |
|------|---------|
| `services/fiscal/calculators.py` | Tax calculation functions and rate tables |
| `routers/portal/fiscal.py` | Route handler |
| `templates/portal_fiscal.html` | Page template |
| `migrations/047_issuer_fiscal_profile.sql` | DB table for regime selection |
| `tests/test_fiscal_calculators.py` | Unit tests (25+ cases) |
| `tests/test_fiscal_route.py` | Route smoke test |

## Limitations

1. **Estimates only** — real tax returns require cumulative annual calculations, not just monthly
2. **RESICO annual limit** — if annual income exceeds $3.5M MXN, taxpayer must switch to PFAE General (not enforced here)
3. **No PM support** — Persona Moral (corporate) tax is not implemented
4. **ISR retenciones** — uses `retenciones` from `sat_cfdi` which may include both ISR and IVA retenciones mixed; proper separation requires XML parsing
5. **PPD timing** — income from PPD invoices is recognized when payment complement is received, not when invoice is issued

## Future Improvements

- Cumulative annual ISR calculation (pagos provisionales acumulados)
- PM General regime support
- XML-based retenciones breakdown (ISR vs IVA)
- Export to PDF/Excel for accountant review
- Integration with month close workflow
