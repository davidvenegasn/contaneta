# Facturapi Integration Guide (for Devs & Contadores)

## Overview

ContaNeta uses [Facturapi](https://facturapi.io) as its PAC (Proveedor Autorizado de Certificación) to stamp CFDI invoices. This guide explains the current integration, planned flows, and what's pending.

## Current Implementation

### What Works Today

1. **Emit CFDI Ingreso (I)**: Standard income invoices with items, taxes, multi-currency
2. **Download XML/PDF/ZIP**: From Facturapi or local storage
3. **Cancel CFDI**: All 4 SAT motive codes supported
4. **Replace CFDI (Nota de Crédito)**: Auto-cancel original + emit replacement
5. **Complemento de Pago (P)**: Basic emission via form

### Key Files

| File | Purpose |
|------|---------|
| `facturapi_client.py` | HTTP wrapper (4 endpoints) |
| `services/invoices/invoices_engine.py` | Payload builder |
| `services/invoices/invoices_service.py` | Validation |
| `routers/api/invoices.py` | API endpoints |
| `routers/invoicing.py` | Form-based emission |

### Configuration

```bash
# .env
FACTURAPI_SECRET_KEY=sk_live_...     # Production key
FACTURAPI_TEST_KEY=sk_test_...       # Sandbox key (safe to test)
```

Each issuer needs a `facturapi_org_id` in the `issuers` table to route API calls to the correct Facturapi organization.

## Planned Flows (Not Yet Implemented)

### Factura Global
- **Use case**: Retail — consolidate POS sales without individual RFC
- **Receptor**: XAXX010101000 (genérico nacional)
- **Frequency**: Monthly consolidation
- **Status**: Skeleton in `facturapi_v2.py.template`

### Factura de Exportación
- **Use case**: Services exported to US/EU clients
- **Key**: IVA at 0% for exported services
- **Receptor RFC**: XEXX010101000 (foreign)
- **Status**: `export_code` field exists, validation pending

### Webhook Handling
- **Use case**: Track cancellation responses from SAT
- **Endpoint**: `/api/webhooks/facturapi` (planned)
- **Events**: invoice.cancelled, invoice.status_updated

## How Tax Calculations Work

### IVA (16%)
- **Traslados**: IVA charged to customer (16% of subtotal)
- **Retenciones**: IVA withheld by customer (common in B2B services)
- **Net IVA**: Traslados - Retenciones

### ISR Retenciones
- Common in services: 10% ISR retained by client
- Tracked in invoice items as `retencion_isr`

### PPD vs PUE
- **PUE**: Payment in one installment. IVA caused at emission.
- **PPD**: Payment deferred/in installments. IVA caused at PAYMENT time (via complemento de pago).

## Warnings

1. **NEVER test with production keys** — use `FACTURAPI_TEST_KEY` for sandbox
2. **Cancellation is irreversible** after SAT accepts it (72h window for motive 01)
3. **Multi-org isolation is critical** — wrong `facturapi_org_id` = wrong company's invoices
4. **Exchange rates for USD/EUR invoices** must use DOF rate (Banxico) per SAT rules

## Adding New Invoice Types

1. Add function skeleton to `facturapi_v2.py.template`
2. Build payload in `invoices_engine.py:build_facturapi_payload()`
3. Add validation in `invoices_service.py`
4. Create API endpoint in `routers/api/invoices.py`
5. Add UI form/button in templates
6. Test in sandbox first

## Next Steps

1. **Sandbox testing**: Verify all existing flows work
2. **Webhook endpoint**: Essential for cancellation tracking
3. **Factura Global**: High priority for retail clients
4. **Payment reconciliation**: Link REPs to PPD invoices
5. **Accountant review**: Validate tax calculations match SAT expectations
