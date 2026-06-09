# Research: Portal Polish Fase 1 — CSS-only polish

**Date:** 2026-06-09

## 1. Hairline dividers

### Current tokens
- `--border: rgba(0,0,0,0.06)` (portal_tokens.css:64, light)
- `--border: rgba(255,255,255,.08)` (portal.css:3738, nightmode)
- `--border-strong: rgba(0,0,0,0.12)` (portal_tokens.css:65, light)
- No `--border-hairline` exists yet.

### Hardcoded borders to fix (grayscale only — semantic color borders are intentional)
| File | Line(s) | Selector | Value |
|------|---------|----------|-------|
| portal.css | 2994 | `.month-picker__trigger` | `1.5px solid #e5e7eb` |
| portal.css | 3005 | `.month-picker__trigger:hover` | `border-color: #d1d5db` |
| portal.css | 3017 | `.month-picker__trigger-icon` | `1.5px solid #e5e7eb` |
| portal.css | 3025 | `.month-picker__trigger-icon:hover` | `border-color: #d1d5db` |
| components.css | 1138 | `.dev-debug-panel__list` | `1px solid #e2e8f0` |
| components.css | 1141 | `.dev-debug-panel__clear` | `1px solid #e2e8f0` |
| components.css | 1144 | `.dev-debug-panel__item` | `border-bottom: 1px solid #f1f5f9` |
| form.css | 1114 | `input[type="checkbox"]` | `1.5px solid #d1d5db` |
| form.css | 1233 | `.inline-check__input` | `1.5px solid #d1d5db` |
| form.css | 1326 | `.checkline input[type="checkbox"]` | `1.5px solid #d1d5db` |

### Decision
- Define `--border-hairline` as a value token (color only, not shorthand) in portal_tokens.css.
  - Light: `rgba(0,0,0,0.06)` (same as `--border`)
  - Night: `rgba(255,255,255,0.08)` (same as nightmode `--border`)
- For month-picker triggers and checkboxes use `var(--border-strong)` / `var(--border)` since they are interactive controls, not pure decorative hairlines.
- Dev-debug-panel: replace with `var(--border)`.
- Semantic color borders (warning, danger, impersonation) — leave as-is (they're intentional accent colors).

**Scope:** ~10 lines changed across 3 CSS files, plus 2 token definitions.

---

## 2. `font-variant-numeric: tabular-nums` on amounts

### Already applied
- `.metric-value` (portal.css:785)
- `.bank-monto-ingreso/gasto/traspaso` (portal.css:3339-3380)
- `.table .text-right` (portal.css:3641, portal_components.css:172)
- `.numeric` (portal_components.css:171)
- Combined selector at portal.css:3649 covers `td[class*="monto"]`, `.metric-value`, `.ui-kpi-card__value`
- `.pv2-balance-amount`, `.pv2-balance-btn-value` (portal_dashboard_v2.css)
- `.concil-pct` (portal.css:7959)
- `.ui-kpi-card__value` (portal_ui_v2.css:385-386)

### Missing — need to add
| Selector | File | Reason |
|----------|------|--------|
| `.provider-invoice-card__total` | portal.css:4635 | Invoice total in card, no tabular-nums |
| `.invoice-card-mobile__total` | portal.css:5195 | Mobile invoice total |
| `.cfdi-detail-total` | portal.css:5487 | CFDI detail view total |
| `.sticky-action-card .pill#action_total_text` | form.css:1427 | Form totals card |
| `.quick-invoice-modal__total-row` | portal_components.css:114 | Quick invoice modal totals |
| `.action-total` | form.css:957 | Totals display |

### Decision
Add a single catch-all rule in portal.css to cover all amount/total selectors that are missing tabular-nums.

---

## 3. Hover lift on interactive cards

### Already implemented (no changes needed)
- `.card:hover` → `translateY(-1px)` + shadow (portal.css:649, animations.css:51)
- `.metric-card:hover` → `translateY(-2px)` + shadow (portal.css:756)
- `.card--interactive:hover` → `translateY(-2px)` + shadow (components.css:200)
- `.actions-card__grid-item:hover` → `translateY(-2px) scale(1.02)` + shadow (portal.css:7812)
- `.actions-card__item:hover` → `translateY(-1px)` + shadow (portal.css:7713)
- `.provider-invoice-card:hover` → shadow (portal.css:4594)
- Transitions pre-declared on `.card`, `.ui-card` base classes

### Missing
| Selector | File | Issue |
|----------|------|-------|
| `.provider-invoice-card` | portal.css | Has :hover shadow but NO transform lift |

### Decision
Add `transform: translateY(-1px)` to `.provider-invoice-card:hover`. Everything else is already well-covered. This is a minimal change.

---

## 4. Focus rings

### Current system
- `--focus-ring: 2px solid var(--accent)` (portal_tokens.css:110)
- `--focus-ring-offset: 2px` (portal_tokens.css:111)
- `--focus: rgba(99,102,241,.22)` (portal_tokens.css:109)
- `--shadow-focus: 0 0 0 3px var(--accent-soft)` (portal_tokens.css, shadows section)
- Global `:focus-visible` in accessibility.css:40 → `outline: 2px solid var(--primary); outline-offset: 2px`
- Portal tokens also define focus-visible styles at portal_tokens.css:226-233

### Problem: Blanket suppression
portal.css:1743-1749 has:
```css
button:hover, button:focus, button:active, button:focus-visible,
.btn:hover, .btn:focus, .btn:active, .btn:focus-visible,
.icon-btn:hover, .icon-btn:focus, .icon-btn:active,
...
{ box-shadow: none !important; }
```
And nightmode copy at portal.css:3805-3809.

This nukes the `box-shadow: var(--shadow-focus)` that components.css sets on `:focus-visible`. The global `:focus-visible { outline: ... }` in accessibility.css survives since it uses `outline`, not `box-shadow`.

### Many `outline: none` declarations
~25 instances across files. Most are paired with a `box-shadow` focus indicator, BUT the blanket suppression above may override them.

### Decision
- The accessibility.css global `:focus-visible { outline: 2px solid var(--primary); outline-offset: 2px; }` is the actual working focus ring. It uses `outline`, unaffected by the `box-shadow: none !important`.
- Leave the blanket suppression as-is (it prevents unwanted box-shadow on hover/active which is intentional design).
- Verify that all `outline: none` on `:focus-visible` blocks ALSO have a visible alternative. The ones in components.css pair `outline: none` with `box-shadow: var(--shadow-focus)` — but the blanket suppression kills the box-shadow. **Fix**: Remove the `:focus-visible` from the blanket suppression line, so `box-shadow: var(--shadow-focus)` survives on keyboard focus.
- Alternatively, change components.css focus-visible from `box-shadow` to `outline` to be consistent with accessibility.css approach. This is simpler and more robust.

**Recommended approach**: Unify on `outline`-based focus rings everywhere. Change components.css `:focus-visible` rules from `outline: none; box-shadow: var(--shadow-focus)` to `outline: var(--focus-ring); outline-offset: var(--focus-ring-offset)`.

---

## 5. Button press feedback

### Already implemented
- `.btn-primary:active` → `translateY(0)` + reduced shadow (components.css:101)
- `.btn-secondary:active` → `translateY(0) scale(0.98)` (form.css:480-ish)
- `.ui-btn:active` → `scale(0.97)` (animations.css:71)
- `.btn-primary:active` → `translateY(0) scale(0.97)` (animations.css:77)
- Onboarding `.btn-primary:active` → `scale(0.98)` (onboarding.css:254)

### Missing
| Selector | File | Issue |
|----------|------|-------|
| `.btn-ghost:active` | components.css | No `:active` state at all |
| `.icon-btn:active` | components.css | No `:active` state |

### Decision
Add `:active { transform: scale(.97) }` to `.btn-ghost` and `.icon-btn` in components.css. Add `transition: transform 80ms ease` if not already present. The `.icon-btn` already has `transition` on background/border/box-shadow — add `transform` to that list.

---

## 6. Letter-spacing tightening on headings

### Already implemented
- `.page-title` → `letter-spacing: var(--ls-tight)` (portal.css:1548) — `--ls-tight: -0.03em`
- `.section-title` → `letter-spacing: var(--ls-tight)` (portal_components.css:144)
- `.metric-value` → `letter-spacing: var(--ls-tight, -0.02em)` (portal.css:783)
- `.card h1/h2/h3` → `letter-spacing: var(--ls-tight, -0.015em)` (portal.css:657)
- `.portal h2/h3` → `letter-spacing: var(--ls-tight)` (portal_components.css:149-150)
- `--heading-tracking: -0.02em` applied via `.portal-shell-wrap` (portal.css:8314, 8373)
- `h2` in form.css → `letter-spacing: -0.02em` (form.css:56)

### Decision
Already well-covered. No changes needed for letter-spacing. The system is consistent.

---

## Summary: Actual work for Fase 1

| Item | Status | Effort |
|------|--------|--------|
| 1. Hairline dividers | ~10 lines across 3 files + 2 tokens | Small |
| 2. tabular-nums | ~6 selectors to add | Small |
| 3. Hover lift | 1 selector (provider-invoice-card) | Trivial |
| 4. Focus rings | Unify to outline-based, fix blanket suppression | Medium |
| 5. Button press | 2 selectors (btn-ghost, icon-btn) | Trivial |
| 6. Letter-spacing | Already done — no changes | Zero |

**Risk:** Item 4 (focus rings) is the most impactful — changing from `box-shadow` to `outline` on button focus could slightly change visual appearance. Need to verify nightmode.

**Tests baseline:** Run before starting implementation.
