# Programmer Log: Portal Polish Fase 1 — CSS-only polish

**Date:** 2026-06-09

## Changes Made

### 1. Hairline dividers — hardcoded hex → tokens
- `portal.css`: month-picker trigger borders `#e5e7eb` → `var(--border-strong)`, hover `#d1d5db` → `var(--primary)`, hover bg `#f9fafb` → `var(--surface-hover)`
- `components.css`: dev-debug-panel borders `#e2e8f0`/`#f1f5f9` → `var(--border)`
- `form.css`: 3 checkbox border declarations `#d1d5db` → `var(--border-strong)`

### 2. tabular-nums on missing amount selectors
- `portal.css`: Extended combined selector to include `.provider-invoice-card__total`, `.invoice-card-mobile__total`, `.cfdi-detail-total`, `.action-total`, `.quick-invoice-modal__total-row`

### 3. Hover lift on provider-invoice-card
- `portal.css`: Added `transform: translateY(-1px)` to `.provider-invoice-card:hover`
- Added `transform` to base transition property list

### 4. Focus rings — unified on outline
- `components.css`: Changed 4 `:focus-visible` blocks from `outline: none; box-shadow: var(--shadow-focus)` to `outline: var(--focus-ring); outline-offset: var(--focus-ring-offset)`
  - Global portal focusables (button, a, input, select, textarea)
  - `.btn:focus-visible`
  - `.btn-secondary:focus-visible`
  - `.icon-btn:focus-visible`
- This approach is immune to the blanket `box-shadow: none !important` in portal.css

### 5. Button press feedback
- `components.css`: Added `.btn-ghost:active { transform: scale(.97); }`
- `components.css`: Added `.icon-btn:active { transform: scale(.97); }`
- Added `transform 80ms ease` to `.icon-btn` transition list

### 6. Letter-spacing — SKIPPED (already done)

### Fix: test_portal_preload.py
- Removed `test_view_transitions_css_present` and `test_reduced_motion_disables_view_transitions` — View Transitions CSS was intentionally removed by user after artifacts issue
- Replaced with `test_reduced_motion_respected_globally` that checks the general prefers-reduced-motion block

## Test Results
- 879 passed, 3 failed (pre-existing FIEL badge), 4 skipped
- 0 new failures
