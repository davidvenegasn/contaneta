# Facturapi Integration — Roadmap & Gap Analysis

**Date:** 2026-05-12

## Current State

The codebase has a **partial Facturapi integration** via `facturapi_client.py` (56 lines). It wraps 4 API endpoints:

| Endpoint | Function | Status |
|----------|----------|--------|
| `POST /v2/invoices` | `create_invoice()` | Production |
| `GET /v2/invoices/{id}/{format}` | `download_invoice()` | Production |
| `DELETE /v2/invoices/{id}` | `cancel_invoice()` | Production |
| `GET /v2/invoices/{id}` | `get_invoice()` | Defined, unused |

**Auth**: Bearer token via `FACTURAPI_SECRET_KEY`. Organization routing via `Facturapi-Organization` header using `issuers.facturapi_org_id`.

**No sandbox/prod distinction** — the key itself determines environment.

## Invoice Types — Coverage Matrix

| Type | Code | Status | Notes |
|------|------|--------|-------|
| CFDI Ingreso | I | FULL | Quick invoice, form, bulk |
| Nota de Crédito | E/N | FULL | Via `replaces_uuid` + relationship "04" |
| Complemento de Pago | P | PARTIAL | Emit only, no reconciliation |
| Cancelación | — | FULL | Motives 01-04, auto-cancel on replacement |
| Factura Global | I (global) | MISSING | No dedicated flow |
| Factura Exportación | I (export) | PARTIAL | `export_code` field exists, no validation |
| Comercio Exterior | — | MISSING | Complemento not implemented |
| Webhooks | — | MISSING | No endpoint |

## Gap Analysis by Feature

### 1. CFDI Ingreso Simple (B2B Normal) — IMPLEMENTED
**Status**: Production-ready via `/api/invoices/quick` and `/invoicing/submit`.

Payload builder in `services/invoices/invoices_engine.py:209` handles:
- Customer data (RFC, name, fiscal regime, CFDI use)
- Line items (product key, description, qty, unit price)
- Tax calculations (IVA traslados, retenciones)
- Currency and exchange rate
- Payment method and forma de pago

### 2. Factura Global (Público en General) — NOT IMPLEMENTED
**When emitted**: Consolidation of sales to "público en general" (no RFC) for a period.
**Required fields**:
- Receptor: `XAXX010101000` (genérico nacional)
- RFC receptor use: `S01` (Sin obligaciones fiscales)
- `Periodicidad`: 01-monthly, 02-bimonthly, 03-quarterly, 04-daily, 05-monthly
- `Meses`: 01-12 (month covered)
- `Año`: 2026

**Gap**: No endpoint, no UI, no batch aggregation logic.

### 3. Factura de Exportación — PARTIAL
**When emitted**: Services/goods exported. CFDI keys: A-A (export definitiva de bienes), A-B (temporal), A-C (none — most services).
**Current**: `export_code` parameter exists (default "01" = no export).
**Gap**: No validation for export-specific fields (pedimento aduanal, número de permiso). No CFDI use code enforcement (`P01` for export services).

### 4. Nota de Crédito — IMPLEMENTED
**How it works**: Create new CFDI type E/N with `replaces_uuid` pointing to original. System auto-cancels original with motive "01" after new one is stamped.
**Database**: `replaces_uuid`, `replacement_uuid`, `cancel_status` columns.

### 5. Cancelación — IMPLEMENTED
**Motive codes**:
- `01`: Con comprobante que sustituye (with replacement)
- `02`: Comprobantes emitidos con errores sin relación
- `03`: No se llevó a cabo la operación
- `04`: Operación nominativa relacionada en factura global

**Flow**: `POST /api/invoices/{uuid}/cancel` → Facturapi DELETE → update local DB → mark as cancelled.

### 6. Complemento de Pago — PARTIAL
**Current**: Can emit P-type CFDI via form. Tracks payment relations in `payment_relations` table.
**Gap**: No reconciliation against PPD invoices, no saldo pendiente tracking, no REP webhook handling.

### 7. Webhooks — NOT IMPLEMENTED
**Recommended Facturapi webhooks**:
- `invoice.created` — Confirmation after stamping
- `invoice.cancelled` — SAT cancellation accepted/rejected
- `invoice.status_updated` — Status changes (especially for PPD)

**Recommended endpoint**: `POST /api/webhooks/facturapi` with HMAC signature verification.

## Sandbox Testing Checklist

- [ ] Create sandbox account at facturapi.io
- [ ] Set `FACTURAPI_TEST_KEY` in `.env`
- [ ] Emit test CFDI Ingreso (verify UUID, PDF, XML)
- [ ] Download XML/PDF/ZIP
- [ ] Cancel with motive 02
- [ ] Emit replacement (motive 01)
- [ ] Emit complemento de pago (type P)
- [ ] Verify error handling (invalid RFC, expired FIEL, etc.)
- [ ] Test webhook delivery (if implemented)
- [ ] Verify multi-tenant isolation (different org IDs)

## Recommended Next Steps (Prioritized)

1. **Sandbox testing** with existing implementation
2. **Webhook endpoint** for cancellation status updates
3. **Factura Global** flow (high volume for retail clients)
4. **Payment reconciliation** for PPD (link REP to original invoices)
5. **Export invoice validation** (for services exported to US/EU)
6. **Complemento de Comercio Exterior** (lower priority)
