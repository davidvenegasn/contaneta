# Mobile Breakpoints & Responsive Strategy

## Canonical Breakpoints

| Breakpoint | Target | Key changes |
|------------|--------|-------------|
| `1099px` | Desktop sidebar collapse | Rail collapses; hamburger appears (portal_rail.css) |
| `960px` | Dashboard v2 balance | Balance card stacks to full-width row (portal_dashboard_v2.css) |
| `768px` | Primary mobile | Tables scroll, grids stack, forms full-width, CFDI drawer stacks, touch targets 44px (responsive.css) |
| `640px` | Compact mobile | Invoice table → card view toggle (portal.css), reduced table min-widths, search form full-width |
| `480px` | Small phones | Rail shrinks to 48px, modal fullscreen, onboarding stepper compact, settings tabs wrap |
| `419px` | Very narrow | KPI grids → 1-column, section headers stack |
| `390px` | Ultra-narrow | Zero horizontal scroll; overflow hidden on shell |
| `384px` | Galaxy Fold | Onboarding labels hidden, section headers column |

## Touch-device guard

```css
@media (max-width: 768px) and (pointer: coarse) { ... }
```

Used for touch-only overrides: 44px min tap targets, 16px input font (prevents iOS auto-zoom).

## File Responsibilities

| File | Scope |
|------|-------|
| `portal.css` | Base component styles + invoice card-mobile system + 390/419/640px invoice-specific rules |
| `portal_rail.css` | Sidebar/rail collapse at 1099px, hamburger toggle |
| `portal_dashboard_v2.css` | Dashboard v2 balance card at 960px |
| `responsive.css` | Cross-cutting responsive fixes loaded LAST: tables, grids, forms, modals, typography, touch targets |

## Table → Card Pattern (invoices)

Desktop shows `<table>` inside `.card--invoice-list .table-wrap`. Mobile shows `.invoice-list-mobile` with `.invoice-card-mobile` cards.

Toggle in `portal.css`:
```css
@media (max-width: 640px) {
  .card--invoice-list .table-wrap { display: none !important; }
  .invoice-list-mobile { display: flex; }
}
@media (min-width: 641px) {
  .invoice-list-mobile { display: none !important; }
}
```

## Safe-area Support

Notched devices handled via `env(safe-area-inset-*)` in:
- Modal headers/footers (responsive.css)
- Movement/invoice/CFDI drawer panels (responsive.css)

## Testing Checklist

Test at these Chrome DevTools presets:
1. **iPhone SE** (375×667) — ultra-narrow, verify no horizontal scroll
2. **iPhone 14 Pro** (393×852) — standard iOS, verify touch targets
3. **Pixel 7** (412×915) — standard Android
4. **iPad Mini** (768×1024) — tablet boundary, verify grid transitions
