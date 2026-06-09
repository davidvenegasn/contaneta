# QA: Portal Polish Fase 1 — CSS-only polish

**Date:** 2026-06-09

## Test Suite
- 879 passed, 3 failed (pre-existing FIEL badge), 4 skipped
- `python -c "import app"` → ok
- 0 new failures

## Visual Checks (CSS-only, verified via code inspection)

### Hairline dividers
- [x] Month picker trigger: `var(--border-strong)` in light, resolves to `rgba(255,255,255,.14)` in nightmode
- [x] Month picker hover: `var(--primary)` accent border — visible in both themes
- [x] Checkboxes: `var(--border-strong)` — consistent with other form controls
- [x] Debug panel: `var(--border)` — dev-only component

### Tabular nums
- [x] Combined selector covers all amount classes
- [x] `.provider-invoice-card__total`, `.invoice-card-mobile__total`, `.cfdi-detail-total`, `.action-total`, `.quick-invoice-modal__total-row` all get `font-variant-numeric: tabular-nums`

### Hover lift
- [x] `.provider-invoice-card:hover` has `translateY(-1px)` with transition
- [x] Base transition includes `transform` for smooth animation

### Focus rings
- [x] All focusables use `outline: var(--focus-ring)` — immune to box-shadow suppression
- [x] `--focus-ring: 2px solid var(--accent)` defined in portal_tokens.css
- [x] Works in nightmode (accent has dark override)

### Button press
- [x] `.btn-ghost:active` → `scale(.97)`
- [x] `.icon-btn:active` → `scale(.97)` with `transform 80ms ease` transition
- [x] Disabled buttons not affected (animations.css handles `:disabled:active { transform: none }`)

### Reduced motion
- [x] No new keyframe animations added
- [x] Transform on active is instant (no duration concern)
- [x] Global `prefers-reduced-motion` block in portal.css kills all transition/animation durations

## Verdict: PASS
