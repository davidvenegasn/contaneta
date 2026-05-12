# Mobile Responsive Audit

**Date:** 2026-05-12
**Method:** Playwright headless browser screenshots at 375px (iPhone SE), 390px (iPhone 12), and 768px (iPad). Horizontal overflow detection via DOM `scrollWidth` comparison.

## Summary

The portal is **well-adapted for mobile**. All critical pages render without horizontal overflow at 375px. The CSS uses a comprehensive breakpoint system with 76 `@media` queries in `portal.css` alone (142 total across all CSS files).

**Verdict: No critical mobile issues found. Minor cosmetic observations noted below.**

## Breakpoint System

| Breakpoint | Purpose |
|-----------|---------|
| `1200px` | Topbar truncation |
| `1100px` | Dashboard grid → 2 columns, sidebar collapse |
| `980px` | Minor layout adjustments |
| `900px` | Topbar user text hidden |
| `768px` | Primary mobile breakpoint — stacked layouts, bottom nav visible |
| `640px` | Table/grid adjustments |
| `480px` | Compact mobile — smaller padding, fonts |
| `419px` | KPI grid → 1 column |
| `390px` | iPhone-specific adjustments |
| `380px` | Ultra-compact — minimal padding |

## Page-by-Page Results

### `/portal/home` (Dashboard)
- **Status:** OK
- **Mobile rules:** Yes — KPI grid 2×2 at 768px, 1-col at <419px. Bottom navigation bar. Sidebar collapses to drawer.
- **Overflow:** None (375px: doc=375, view=375)
- **Notes:** Clean layout, activity feed readable, quick actions accessible via bottom nav FAB.

### `/portal/facturas` (Issued/Received invoices)
- **Status:** OK
- **Mobile rules:** Yes — summary cards stack, table wrapped in `.table-wrap` with `overflow-x: auto`. Tab bar responsive.
- **Overflow:** None
- **Notes:** Invoice table horizontally scrollable. Filters and export button accessible.

### `/portal/bank/movements`
- **Status:** OK
- **Mobile rules:** Yes — KPI cards in 2×2 grid at mobile. Movement table in scrollable wrapper.
- **Overflow:** None
- **Minor:** At 768px, "Cuenta propia" metric card shows "Entradas" and "Salidas" values slightly tight. Not broken — cosmetic only.

### `/portal/catalogos?tab=clientes`
- **Status:** OK
- **Mobile rules:** Yes — tabs stack, search field full-width, table scrollable.
- **Overflow:** None (products table extends to 399px at 375px viewport but contained by `overflow-x: auto` on parent).

### `/portal/catalogos?tab=productos`
- **Status:** OK
- **Mobile rules:** Yes — same as clientes tab.
- **Overflow:** Contained by scroll wrapper.

### `/login`
- **Status:** OK
- **Mobile rules:** Yes — card uses `max-width` with padding, inputs full-width. Form.css has 25 media queries.
- **Overflow:** None
- **Notes:** Clean, centered card. Google OAuth button, forgot password link all accessible.

### `/register`
- **Status:** OK
- **Mobile rules:** Yes — same form system as login.
- **Overflow:** None

### `/pricing`
- **Status:** OK
- **Mobile rules:** Yes — plan cards stack vertically at mobile widths.
- **Overflow:** None
- **Notes:** Comparison table uses accordions on mobile (collapsible sections).

## CSS Coverage Summary

| CSS File | `@media` queries | Mobile-specific |
|----------|-----------------|----------------|
| `portal.css` | 76 | Yes — extensive (768px, 480px, 419px, 380px) |
| `form.css` | 25 | Yes — input sizing, label stacking |
| `components.css` | 12 | Yes — modals, cards, buttons |
| `portal_rail.css` | 7 | Yes — sidebar/rail collapse |
| `portal_sidebar_unified.css` | 5 | Yes — sidebar drawer mode |
| `portal_components.css` | 4 | Yes — table overflow |
| `portal_dashboard_v2.css` | 3 | Yes — dashboard grid |
| `portal_shell_v2.css` | 2 | Yes — shell layout |
| `portal_shell.css` | 1 | Minimal |
| `auth.css` | 0 | N/A — link colors only, layout handled by `form.css` |

## Key Mobile Features

1. **Bottom navigation bar** — 5-tab bar (Inicio, Facturas, Nueva, Movimientos, Menú) with FAB for "Nueva"
2. **Sidebar → drawer** — Desktop sidebar collapses to hamburger-triggered drawer on mobile
3. **Scrollable tables** — `.table-wrap` with `overflow-x: auto` and `-webkit-overflow-scrolling: touch`
4. **Viewport meta** — All templates include `<meta name="viewport" content="width=device-width, initial-scale=1">`
5. **Safe area insets** — `base_portal.html` uses `viewport-fit=cover` with CSS `env(safe-area-inset-*)` for notched devices
6. **Reduced motion** — 11 `prefers-reduced-motion` queries for accessibility
7. **KPI responsive grid** — Auto-fit with `minmax(220px, 1fr)`, drops to 2-col then 1-col

## Fixes Applied

None required — no critical mobile issues found.

## Screenshots

Captured at `/tmp/mobile_screenshots/` (iPhone 12 390×844 @3x):
- `home_iphone12.png`
- `facturas_iphone12.png`
- `bank_iphone12.png`
- `clientes_iphone12.png`
- `login_iphone12.png`
