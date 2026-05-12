# PPD (Pago en Parcialidades o Diferido) — Audit

**Date:** 2026-05-12

## Current Flow

```
User visits /portal/facturas?tab=ppd
  → routers/portal/invoices.py:portal_facturas_hub()
    → Queries sat_cfdi WHERE direction='received' (NO metodo_pago filter)
    → Calls get_month_totals(issuer_id, ym, "received")  ← BUG: no PPD filter
    → Sets default_metodo_pago="PPD" for frontend
  → Template: partials/ppd_list.html → includes received_list.html
    → Frontend JS calls API with metodo_pago=PPD → table rows ARE filtered
    → Summary cards show UNFILTERED totals (all received, not just PPD)
```

## Bug: PPD Summary Totals Include All Received Invoices

**File:** `services/sat/sat_sync.py:60` (`get_month_totals`)
**Impact:** HIGH — accounting metrics incorrect for PPD-specific view

When user views the PPD tab:
- **Table rows**: Correctly filtered to metodo_pago=PPD (frontend JS passes filter to API)
- **Summary cards** (Total egresos, IVA pagado, Retenciones IVA pagadas): Show ALL received invoices (PUE + PPD combined), NOT just PPD

### Fix Applied

Added `metodo_pago` parameter to `get_month_totals()`:
- `services/sat/sat_sync.py`: `def get_month_totals(issuer_id, ym, direction, metodo_pago=None)` — appends `UPPER(TRIM(COALESCE(metodo_pago,''))) = ?` when set
- `routers/portal/invoices.py`: Passes `metodo_pago="PPD"` for PPD tab

## Discrepancies vs Mexican Tax Rules

### 1. IVA Timing for PPD (CRITICAL — NOT YET ADDRESSED)
- **SAT rule**: For PPD invoices, IVA is "caused" (causado) when PAYMENT is received, not when the invoice is emitted.
- **Current implementation**: IVA totals use invoice emission date, not payment date.
- **Impact**: Overstates IVA causado/acreditable in the month of emission; understates in the month of actual payment.
- **Fix complexity**: HIGH — requires tracking complementos de pago (REP) and linking them to original PPD invoices.

### 2. No Complemento de Pago (REP) Tracking
- No dedicated table or logic for tracking complementos de pago.
- SAT sync captures REP as separate CFDI records, but they're not linked to original PPD invoices.
- Cannot determine: partial payments received, remaining balance, payment dates.
- **Fix complexity**: MEDIUM-HIGH — needs schema changes and linking logic.

### 3. Saldo Pendiente Not Calculated
- No concept of "outstanding balance" per PPD invoice.
- Users cannot see: how much has been paid, what's still owed.
- **Fix complexity**: MEDIUM — requires REP linking first.

## Recommendations (Prioritized)

| # | Action | Effort | Impact |
|---|--------|--------|--------|
| 1 | **[DONE]** Filter PPD totals by metodo_pago | Small | High |
| 2 | Link REP complementos to original PPD invoices | High | High |
| 3 | Track partial payments and saldo pendiente | Medium | High |
| 4 | Adjust IVA timing to use payment date for PPD | High | Critical for fiscal accuracy |
| 5 | Add PPD aging report (facturas vencidas) | Medium | Medium |

## Schema Changes Needed (NOT Applied)

For items 2-4, new columns/tables would be needed:
```sql
-- Complementos de pago linkage
CREATE TABLE IF NOT EXISTS ppd_payments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  cfdi_uuid TEXT NOT NULL,          -- original PPD invoice UUID
  rep_uuid TEXT NOT NULL,           -- complemento de pago UUID
  monto_pagado REAL NOT NULL,
  fecha_pago TEXT NOT NULL,
  parcialidad INTEGER,             -- payment number (1, 2, 3...)
  saldo_anterior REAL,
  saldo_insoluto REAL,
  created_at TEXT DEFAULT (datetime('now'))
);
```

This requires a human decision on architecture and must be validated with a contador.
