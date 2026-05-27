# Programmer Log: Smart-detect tipo (INGRESO/GASTO) for foreign invoice PDFs

**Date**: 2026-05-27

## Problem
`_pdf_parse_helpers.py:520` had `result["tipo"] = "GASTO"` hardcoded. Freelancers uploading their own invoices (where they are the seller) got GASTO instead of INGRESO.

## Changes

### `routers/api/invoices/_pdf_parse_helpers.py`
- Added `_normalize_for_match()` — lowercase, strip accents, strip punctuation
- Added `_name_words()` — extract significant words from name
- Added `_words_match()` — check if N words from needle appear in haystack
- Added `_detect_tipo(text, issuer_context)` — splits PDF text at "Bill To" marker into seller/buyer blocks, matches issuer name against each
- Changed `_parse_invoice_text()` signature: added `issuer_context=None` parameter
- Replaced hardcoded `"GASTO"` with `_detect_tipo()` call

### `routers/api/invoices/pdf_extract.py`
- Before calling `_parse_invoice_text()`, builds `issuer_ctx` from `issuers` table (razon_social, rfc) + user name as fallback
- When `auto_save=True` and tipo is None: returns `{tipo_undetected: True, needs_user_confirm: True}` instead of auto-saving with wrong tipo

### `static/js/movement-modal.js`
- `openAddInvoiceModal()`: sets tipo toggle to match backend-detected tipo
- `prefillInvoiceForm()`: same toggle sync
- `_processNext()`: shows "Confirma si es ingreso o gasto" toast when `tipo_undetected`

## Detection Logic
1. Extract seller block: first ~10 non-empty lines before "Bill To" / "Invoice To" / "To:" marker
2. Extract buyer block: up to 8 lines after the marker
3. Normalize issuer name (razon_social or nombre): strip accents, lowercase, split into words
4. Match words against each block (min 2 words, or 1 for single-word names)
5. If issuer in seller → INGRESO; if in buyer → GASTO; otherwise → None

## Edge Cases NOT Handled
- **Scanned PDFs** (images without OCR): no text extracted, rejected earlier in pipeline
- **Razón social very different from business name**: e.g. "PCJC Consulting SA de CV" vs "Perla Chavez" — would return None
- **PDFs without "Bill To" section**: e.g. simple receipts — seller block = entire text, no buyer block → may detect INGRESO or None
- **Both names appear in both sections**: returns None (ambiguous)

## Tests
9 new tests in `tests/test_foreign_invoice_tipo_detection.py`:
- INGRESO when issuer name at top
- GASTO when issuer name in Bill To
- None when unmatched
- None without issuer context
- razon_social preferred over nombre
- Accent normalization
- Empty issuer name → None
- Stripe receipt → GASTO
- "Invoice To" variant → INGRESO

## Results
- Baseline: 606 passed, 4 skipped
- After: 615 passed, 4 skipped (+9 new tests)
