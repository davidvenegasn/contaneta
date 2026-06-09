# Plan: Portal Polish Fase 1 — CSS-only polish

**Date:** 2026-06-09

## Items to implement

### 1. Hairline dividers — replace hardcoded hex borders with tokens
**Files:** portal.css, components.css, form.css

| File | Line | Old | New |
|------|------|-----|-----|
| portal.css | 2994 | `border: 1.5px solid #e5e7eb` | `border: 1.5px solid var(--border-strong)` |
| portal.css | 3005 | `border-color: #d1d5db` | `border-color: var(--primary)` (hover accent) |
| portal.css | 3017 | `border: 1.5px solid #e5e7eb` | `border: 1.5px solid var(--border-strong)` |
| portal.css | 3025 | `border-color: #d1d5db` | `border-color: var(--primary)` (hover accent) |
| components.css | 1138 | `border: 1px solid #e2e8f0` | `border: 1px solid var(--border)` |
| components.css | 1141 | `border: 1px solid #e2e8f0` | `border: 1px solid var(--border)` |
| components.css | 1144 | `border-bottom: 1px solid #f1f5f9` | `border-bottom: 1px solid var(--border)` |
| form.css | 1114 | `border: 1.5px solid #d1d5db` | `border: 1.5px solid var(--border-strong)` |
| form.css | 1233 | `border: 1.5px solid #d1d5db` | `border: 1.5px solid var(--border-strong)` |
| form.css | 1326 | `border: 1.5px solid #d1d5db` | `border: 1.5px solid var(--border-strong)` |

### 2. tabular-nums — add to missing amount selectors
**File:** portal.css (single rule block at end of amounts section)

Add `font-variant-numeric: tabular-nums` to:
- `.provider-invoice-card__total`
- `.invoice-card-mobile__total`
- `.cfdi-detail-total`
- `.action-total`
- `.quick-invoice-modal__total-row`

### 3. Hover lift — provider-invoice-card
**File:** portal.css

Add `transform: translateY(-1px)` to existing `.provider-invoice-card:hover` rule.

### 4. Focus rings — unify on outline
**File:** components.css

Change `:focus-visible` rules from `outline: none; box-shadow: var(--shadow-focus)` to `outline: var(--focus-ring); outline-offset: var(--focus-ring-offset)`.

Affected selectors:
- `.portal button:focus-visible` etc. (line 8-16)
- `.btn:focus-visible` (line 59-64)
- `.btn-secondary:focus-visible` (line 129-133)
- `.icon-btn:focus-visible` (line 290-293)

### 5. Button press — add :active to btn-ghost and icon-btn
**File:** components.css

- `.btn-ghost:active { transform: scale(.97); }`
- `.icon-btn:active { transform: scale(.97); }`
- Add `transform` to `.icon-btn` transition list.

### 6. Letter-spacing — SKIP (already done)

## Risks
- Focus ring change: visual change from shadow to outline. Outline works better with `box-shadow: none !important` suppression. Nightmode-safe because outline inherits from `var(--focus-ring)` which uses `var(--accent)`.
- All changes are CSS-only, no behavior changes.
