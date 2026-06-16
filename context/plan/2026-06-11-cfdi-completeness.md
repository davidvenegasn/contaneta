# Plan: CFDI 4.0 Portal Completeness
Date: 2026-06-11
Research: context/research/2026-06-11-cfdi-completeness.md

## Scope

Implement all CRITICAL + IMPORTANT gaps in the Mexican CFDI 4.0 invoicing portal.
Every feature must be sleek, well-designed, and functionally correct.

---

## What already exists (don't duplicate)

- `invoices` table with `payment_method` (PPD/PUE), `cancel_status`, `cancel_motive`, `replacement_uuid`, `replaces_uuid`
- `payment_relations` table (CFDI P composition rows)
- `customer_profiles` table (rfc, legal_name, zip, tax_system, email)
- `facturapi_client.py`: `create_invoice`, `cancel_invoice`, `download_invoice`, `get_invoice`
- Form partials: `_section_receptor.html` (has cards normal/publico_general/extranjero), `_section_comprobante.html`, `_section_extras.html`
- Cancellation endpoint at `POST /invoices/{uuid}/cancel` with 4 motives (basic)
- CFDI P invoice type partially wired (`parse_payments_from_form`) 
- `exportacion` field (01/02/03) in form
- GlobalCFDI `global_*` fields already in receptor section (partially)

---

## Phase 1 — Fix invoice form CFDI 4.0 compliance gaps [Priority: CRITICAL]

### 1a. Factura al Extranjero — fix missing fields

**Problem:** When `receptor_type=extranjero`, portal emits RFC=XEXX but is missing:
- `ResidenciaFiscal` (ISO country code) — mandatory
- `NumRegIdTrib` (foreign tax ID) — required when provided
- `Exportacion` doesn't auto-set to `02` for goods
- `UsoCFDI` doesn't auto-force `S01`
- `RegimenFiscalReceptor` doesn't auto-force `616`

**Changes:**
- `templates/form/_section_receptor.html`: Add "País de residencia fiscal" country dropdown (ISO codes) + "ID fiscal extranjero" text input, both visible only when extranjero card is selected
- `services/invoices/engine.py` (or equivalent builder): When RFC=XEXX, force `customer.tax_system=616`, `cfdi_use=S01`, inject `fiscal_regime=616`, `foreign_id=numregidtrib`, `residence=country_code` into Facturapi customer payload
- Country dropdown: curated list ~30 major countries + "Otro" with free text
- Auto-fill: when extranjero selected, UsoCFDI dropdown auto-selects S01 and disables, régimen auto-selects 616 and disables

### 1b. UsoCFDI × RegimenFiscal validation (client-side + server-side)

**Problem:** SAT rejects CFDI when UsoCFDI is incompatible with receptor's regime. Error CFDI40173/40148 — single highest-frequency rejection.

**Changes:**
- `static/js/invoice-form.js`: Add validation matrix. When `customer_tax_system` changes, filter `cfdi_use` dropdown to only valid options. Show inline warning when incompatible combo is selected.
- Key rules to enforce:
  - D01–D10 only for personas físicas in regimes: 605, 606, 608, 611, 612, 614, 615, 616, 621, 622, 625, 626
  - G01 not for regime 616
  - P01 entirely removed (already removed in 4.0 but may be in dropdown)
  - S01 valid for ALL regimes — set as default/safe
- Server-side: validate in `invoices_engine.py` before building payload, return 422 with clear message

### 1c. ObjetoImp per concept

**Problem:** CFDI 4.0 requires ObjetoImp on each concept. Currently portal probably sends without it.

**Changes:**
- `templates/form/_section_conceptos.html`: Add per-row dropdown with 4 options (01=no sujeto, 02=sí objeto/desglosar, 03=sí objeto/no obligado, 04=sí pero no causa)
- Default: `02` (covers 99% of cases — standard taxed service/product)
- Hide if `01` selected (removes tax row for that concept)
- `services/invoices/engine.py`: Pass `product.tax_included` / `objeto_imp` field to Facturapi payload per item

### 1d. IVA Exento + Tasa 0% + IEPS fix

**Problem:** Current form only offers "IVA 16% / IVA 0% / Sin IVA". This is wrong:
- "Exento" and "Tasa 0%" are different SAT concepts (different TipoFactor)
- IEPS (impuesto 003) not supported

**Changes:**
- `templates/form/_section_conceptos.html`: Change IVA dropdown to:
  - IVA 16% (standard)
  - IVA 8% (fronterizo)
  - IVA 0% (tasa cero — alimentación/medicinas)
  - IVA Exento (educación, etc.)
  - Sin impuesto
- `services/invoices/engine.py`: Map these to correct Facturapi tax structures (type, factor, rate)
- Tooltip/hint explaining difference between "Exento" and "0%"

---

## Phase 2 — CFDI Egreso (Nota de Crédito) [Priority: CRITICAL]

### Overview
A credit note cancels/reduces a prior Ingreso without cancelling the original. The Egreso:
- References the original invoice UUID via `CfdiRelacionados TipoRelacion=01`
- Co-exists with the original (original NOT cancelled)
- Covers: discounts, returns, partial refunds

### Changes:

**New route:** `GET /portal/invoices/{uuid}/nota-credito` → renders credit note form
**New POST:** `POST /invoices/{uuid}/nota-credito` → creates Egreso via Facturapi

**Template:** `templates/nota_credito.html`
- Extends `base_portal.html`
- Header: "Nueva nota de crédito" + original invoice summary card (UUID, receptor, total, date)
- Shows original Ingreso data pre-filled (receptor, RFC, etc.)
- Items section: line-by-line credit, or total credit as single concept
- "Motivo" free-text field
- Total crediting (partial or full)
- Shows running saldo after credit

**DB change:** Add `egreso_of_invoice_id` column to `invoices` table (FK pointing to original Ingreso)

**Button in invoice detail page:** "Emitir nota de crédito" appears on issued Ingreso invoices (not on E, P, T, N)

**service logic:**
- `services/invoices/egreso.py`: `build_egreso_payload(original_invoice, credit_items)` → Facturapi payload with TipoRelacion=01, CfdiRelacionados
- Validates: original must be Ingreso, must be in same issuer, not already fully credited

---

## Phase 3 — PPD + Complemento de Pago 2.0 (REP) [Priority: CRITICAL]

This is the most complex feature. Requires new DB table, new UI flows, and arithmetic.

### 3a. DB migration: PPD payment state tracking

New table `invoice_payments`:
```sql
CREATE TABLE IF NOT EXISTS invoice_payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    issuer_id INTEGER NOT NULL,
    invoice_id INTEGER NOT NULL REFERENCES invoices(id),
    rep_invoice_id INTEGER REFERENCES invoices(id), -- FK to the CFDI P created
    parcialidad INTEGER NOT NULL DEFAULT 1,         -- sequential 1, 2, 3...
    fecha_pago TEXT NOT NULL,                       -- ISO datetime of payment
    forma_pago TEXT NOT NULL,                       -- 03=transferencia, 02=cheque...
    moneda_pago TEXT NOT NULL DEFAULT 'MXN',
    tipo_cambio_pago TEXT,
    monto_pagado REAL NOT NULL,                     -- in moneda_pago
    saldo_anterior REAL NOT NULL,                   -- in moneda of original invoice
    saldo_insoluto REAL NOT NULL,                   -- saldo_anterior - importe_abonado
    num_operacion TEXT,                             -- bank reference
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_invoice_payments_invoice ON invoice_payments(invoice_id);
```

### 3b. PPD invoice detail page enhancements

On `GET /portal/cfdi/issued/{uuid}` (for PPD invoices):
- Show "Saldo pendiente" progress bar: paid vs. remaining
- Show payment history table: date, form, amount, parcialidad #, REP UUID
- CTA button: "Registrar pago recibido" (visible when saldo_insoluto > 0)
- Alert if parcialidad is overdue (> 10th of following month with no REP)

### 3c. New REP creation flow

**Route:** `GET /portal/invoices/{uuid}/registrar-pago` → REP creation form
**POST:** `POST /invoices/{uuid}/registrar-pago` → creates CFDI P + inserts payment row

**Template:** `templates/registrar_pago.html`
- Header: "Registrar pago — [Factura UUID]"
- Original invoice summary: receptor, total, saldo pendiente
- Form fields:
  - Fecha del pago (datetime picker, max=today)
  - Forma de pago (03=transferencia bancaria, 02=cheque, 04=tarjeta, 28=SPEI, etc.)
  - Moneda del pago (default: moneda del invoice)
  - Tipo de cambio (auto-fetched from Banxico FIX if moneda ≠ MXN)
  - Monto recibido (in moneda_pago)
  - Importe abonado a esta factura (auto-calculated, editable for partial)
  - Número de operación/referencia (optional)
- Calculated fields shown live:
  - EquivalenciaDR (shown with formula)
  - Saldo anterior → saldo insoluto after this payment
  - Tax replication preview (IVA proporcional)
- Submit: "Emitir complemento de pago"

**Service logic:**
- `services/invoices/rep.py`: `build_rep_payload(invoice, payment_data, prior_payments)` 
  - Computes NumParcialidad, ImpSaldoAnt, ImpPagado, ImpSaldoInsoluto
  - Computes EquivalenciaDR (formula: ImpSaldoAnt_MonedaDR ÷ equivalent_MonedaP)
  - Replicates IVA proportionally if ObjetoImpDR=02
  - Returns complete Facturapi CFDI P payload
- Banxico FIX API integration: `services/banxico.py` `get_fix_rate(date, moneda)` → calls Banxico SIE API, caches in DB (daily)

### 3d. Multi-invoice REP (advanced)

Allow a single CFDI P to settle multiple PPD invoices from the same receiver in one payment:
- "Agregar otra factura" button on registrar-pago form
- Shows available PPD invoices for that RFC with saldo > 0
- Each added invoice shows: UUID, saldo, importe a abonar (editable)

### 3e. PPD deadline alerts

On `/portal/facturas` (PPD tab):
- Badge "⚠ Complemento pendiente" on PPD invoices past the 10th of next month
- Email/notification: out of scope for now, but hook in jobs table for future

---

## Phase 4 — Cancellation workflow improvements [Priority: CRITICAL]

Current state: basic cancellation works with 4 motives, but:
- Motive 01 doesn't enforce "create replacement first"
- No UI for choosing cancellation motive (probably just a confirm dialog)
- No tracking of pending→accepted→rejected lifecycle

### Changes:

**Cancel modal redesign:**
- `templates/components/cancel_modal.html`: Step-by-step modal
  - Step 1: Choose motive with icons + descriptions:
    - "Contiene errores y emitirás una factura sustituta" (01)
    - "Contiene errores pero no emitirás sustituta" (02)
    - "La operación no se realizó" (03)
    - "El cliente solicitó factura individual de una global" (04)
  - Step 2 (only for motive 01): "¿Ya emitiste la factura sustituta?" 
    - If yes: UUID input field for the replacement
    - If no: disable cancel button, show "Debes emitir primero la factura sustituta"
  - Step 3: Confirmation with motive summary

**Cancellation status badge:**
- In invoice list and detail: show badge "Cancelación pendiente" (orange) while awaiting receptor acceptance
- "Cancelado" (gray) once accepted
- "Cancelación rechazada" (red) if receptor said no

**DB:** `cancel_status` column already exists. Add polling/webhook to update status.

**Replacement link:** On invoice detail of a cancelled invoice with motivo 01, show link to the replacement invoice. On replacement invoice, show "Sustituye a: [UUID]".

---

## Phase 5 — GlobalCFDI (Público en General) [Priority: CRITICAL]

### Context
The form already has `global_*` fields in `_section_receptor.html` when `receptor_type=publico_general`. But let's verify/complete:

**Required `InformacionGlobal` node fields:**
- `Periodicidad`: 01=diaria, 02=semanal, 03=quincenal, 04=mensual
- `Meses`: SAT month code (01=Jan ... 12=Dec) — from `c_Meses` catalog
- `Año`: 4-digit year

**Changes if gaps found:**
- Verify form sends global_periodicity, global_month, global_year
- Verify `invoices_engine.py` maps these to Facturapi's `global_information` payload field
- Add validation: when receptor_type=publico_general, require these 3 fields
- Show info tooltip: "La factura global consolida todas tus ventas al público en ese período"

**New "Factura Global" quick-create:**
- `GET /portal/crear-global` → simplified form:
  - Período (date picker shows last 7 days for daily, last week for weekly, etc.)
  - Total de ventas (single amount input)
  - IVA included/excluded toggle
  - Auto-fills: XAXX, PUBLICO EN GENERAL, 616, S01

---

## Phase 6 — CSD Expiry Management [Priority: CRITICAL]

### Context
CSD certificates have 4-year validity. If they expire, all timbrado fails.

### Changes:

**Read expiry from CSD:** When CSD is uploaded via Facturapi, we can get the certificate info. Add `csd_expires_at` column to `issuers` table.

**Migration:** `ALTER TABLE issuers ADD COLUMN csd_expires_at TEXT;`

**Alert banner:** On all portal pages, if `csd_expires_at` is within 60 days, show a banner:
- 60–31 days: info banner (blue) "Tu CSD vence el {fecha}. Considera renovarlo."
- 30–8 days: warning banner (amber) "Tu CSD vence en {N} días. Renueva para seguir facturando."
- 7–1 days: error banner (red) "⚠ Tu CSD vence mañana. Renueva urgente."
- Expired: blocking error, disable invoice creation

**Settings page:** Show CSD info section with: serial number, issuer name, expiry date, status badge.

**Service:** `services/csd.py` `parse_csd_expiry(cer_bytes)` → uses Python `cryptography` lib to parse X.509 cert and extract `not_valid_after` datetime.

---

## Phase 7 — Banxico FIX API integration [Priority: IMPORTANT]

Needed for: REP EquivalenciaDR, foreign invoices TipoCambio.

**New service:** `services/banxico.py`
```python
def get_fix_rate(date: str, currency: str = "USD") -> Decimal:
    """Fetch Banxico FIX rate for given date and currency.
    Uses SIE API. Caches in exchange_rates table (daily).
    Falls back to most recent available rate if date is weekend/holiday.
    """
```

**DB migration:** New table `exchange_rates`:
```sql
CREATE TABLE IF NOT EXISTS exchange_rates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    currency TEXT NOT NULL,
    rate TEXT NOT NULL,        -- stored as TEXT to preserve precision
    source TEXT DEFAULT 'banxico',
    created_at TEXT DEFAULT (datetime('now')),
    UNIQUE(date, currency)
);
```

**API endpoint:** `GET /api/exchange-rate?date=2026-06-11&currency=USD` → `{ rate: "17.2500", date: "2026-06-11", currency: "USD" }`

**Form integration:**
- Invoice form: when Moneda ≠ MXN, auto-fetch rate on currency change via HTMX/fetch
- REP form: auto-fetch rate on fecha_pago change
- Show: "Tipo de cambio Banxico FIX del {fecha}: ${rate} MXN/{currency} [Actualizar]"

---

## Phase 8 — Retenciones in invoice form [Priority: IMPORTANT]

Current state: `isr_ret_{i}` and `iva_ret_{i}` fields exist per concept but unclear if properly mapped.

**Verify + fix:**
- Verify `parse_items_from_form()` reads retention fields
- Verify `invoices_engine.py` builds Facturapi `taxes` array correctly with retenciones
- Fix UI: make retention fields clearer — "ISR retención (10%)" for honorarios, "IVA retención (10.67%)" for honorarios

**RESICO retención (1.25% ISR):**
- When receptor has `tax_system=626` (RESICO) and issuer is persona moral: auto-add ISR 1.25% retention
- Show info chip: "Retención ISR RESICO aplicada (1.25%)"

---

## Phase 9 — Invoice list UI improvements [Priority: UX]

**PPD tab on `/portal/facturas`:**
- Currently shows all invoices; filter PPD invoices properly
- Column: "Saldo pendiente" showing remaining amount
- Status badges: "Pagado" (green), "Parcial" (blue), "Pendiente" (amber), "Vencido" (red)
- Quick action: "Registrar pago" button per row
- Sort by overdue first

**Issued/Received tab:**
- Add "Tipo" column: badge for I/E/P/T/N with color coding
- Add "Método pago" column: PPD/PUE badge
- Filter by tipo_comprobante
- Egreso invoices show "Nota de crédito" type badge

---

## Implementation Order

1. Phase 1a: Factura extranjero (1-2 hours) — small, high impact
2. Phase 1b: UsoCFDI validation (2 hours) — prevents most SAT rejections
3. Phase 1c: ObjetoImp per concept (1-2 hours)
4. Phase 1d: IVA dropdown fix (1 hour)
5. Phase 7: Banxico API (needed for Phase 3) (2 hours)
6. Phase 6: CSD expiry (2 hours) — ops-critical
7. Phase 4: Cancellation modal redesign (2-3 hours)
8. Phase 2: Egreso / nota de crédito (3-4 hours)
9. Phase 5: GlobalCFDI verification + quick-create (2 hours)
10. Phase 3: PPD/REP full flow (6-8 hours) — largest feature
11. Phase 8: Retenciones cleanup (1 hour)
12. Phase 9: Invoice list UI (2 hours)

---

## Files to create

- `migrations/NNN_invoice_payments.sql` — invoice_payments + exchange_rates tables + CSD expiry column
- `services/invoices/egreso.py` — Egreso payload builder
- `services/invoices/rep.py` — REP payload builder + arithmetic
- `services/banxico.py` — Banxico FIX API + caching
- `services/csd.py` — CSD X.509 expiry parser
- `templates/nota_credito.html` — Credit note form
- `templates/registrar_pago.html` — REP creation form
- `templates/crear_global.html` — Quick GlobalCFDI form (maybe)
- `templates/components/cancel_modal.html` — redesigned cancel modal
- `routers/portal/payments.py` — payment registration routes

## Files to modify

- `templates/form/_section_receptor.html` — extranjero fields + GlobalCFDI complete
- `templates/form/_section_conceptos.html` — ObjetoImp + IVA dropdown
- `templates/form/_section_comprobante.html` — nothing major
- `static/js/invoice-form.js` — UsoCFDI validation matrix, Banxico rate auto-fetch
- `services/invoices/engine.py` — ObjetoImp, extranjero fields, UsoCFDI validation
- `routers/portal/invoices.py` — new buttons, PPD detail enhancements
- `routers/portal/settings.py` — CSD expiry display
- `templates/portal_settings.html` — CSD expiry section
- `templates/base_portal.html` — CSD expiry banner
- `templates/portal_cfdi_issued.html` (or equivalent) — nota de crédito button, REP button

---

## Design principles

- **Sleek, clean, consistent** with existing portal aesthetic (primary=#6366f1, Inter font)
- **Progressive disclosure**: advanced fields hidden until needed (e.g., extranjero fields, EquivalenciaDR formula)
- **Inline validation**: red borders + helper text on invalid combos, not just on submit
- **Smart defaults**: ObjetoImp defaults to 02, UsoCFDI defaults to S01, IVA defaults to 16%
- **Contextual help**: tooltips/popovers on complex fiscal fields explaining what they mean
- **Error surfacing**: SAT rejection codes mapped to human-readable Spanish messages
- **Mobile-aware**: forms must be usable on tablet (accountants use iPads)
