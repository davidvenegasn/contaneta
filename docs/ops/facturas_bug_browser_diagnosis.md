# Facturas Bug — Browser Diagnosis

**Date:** 2026-05-12
**Tool:** Playwright Chromium headless

## Original Report

"In /portal/facturas the invoice list doesn't appear but the total does."

## Findings

### Invoice List: NOT REPRODUCIBLE

The invoice list renders correctly for both months tested:
- **2026-05**: 1 row rendered, table visible, empty state hidden
- **2026-02**: 0 invoices (correct — API returns empty data), empty state shown

The API endpoint `/api/invoices/issued?ym=XXXX` returns 200 with correct data. The JS IIFE in `partials/issued_list.html` calls `window.uiFetchJSON()` → `renderTable()` successfully.

**Hypothesis for original report**: The bug may have been caused by:
1. A transient server error during the specific session
2. A JS error from one of the 500-ing catalog endpoints below blocking execution
3. A stale browser cache

### NEW BUG FOUND: 5 API endpoints returning 500

| Endpoint | Error | Root Cause |
|----------|-------|-----------|
| `/api/catalogs/moneda` | `NameError: _catalog_list` | Missing after API split |
| `/api/catalogs/uso_cfdi` | `NameError: _catalog_list` | Missing after API split |
| `/api/catalogs/forma_pago` | `NameError: _catalog_list` | Missing after API split |
| `/api/catalogs/regimen_fiscal` | `NameError: _catalog_list` | Missing after API split |
| `/api/quick-invoice/bootstrap` | `NameError: _catalog_list` | Missing after API split |

**Root Cause**: When `routers/api.py` was split into feature modules, the `_catalog_list()` helper function and `MONEDA_FALLBACK`, `UNIDAD_FALLBACK`, `PRODSERV_FALLBACK` constants were placed inside `register_operations_routes()` in `operations.py`, making them local to that function scope. The `catalogs.py` and `products.py` modules reference them but never imported them.

**Fix Applied**: Moved `_catalog_list`, `MONEDA_FALLBACK`, `UNIDAD_FALLBACK`, `PRODSERV_FALLBACK` to `routers/api/_helpers.py` (shared module). Updated imports in `catalogs.py` and `products.py`. Removed duplicates from `operations.py`.

**Impact**: Quick invoice creation form was broken (bootstrap endpoint 500). Catalog dropdowns in invoice form were empty. These endpoints now return 200 with correct fallback data.

## Screenshots

- `/tmp/facturas_2026-05.png` — Invoice list rendering correctly (1 invoice)
- `/tmp/facturas_2026-02.png` — Empty state showing correctly (0 invoices)
