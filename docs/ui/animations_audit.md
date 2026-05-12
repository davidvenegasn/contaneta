# Animations & Micro-Interactions Audit

**Date:** 2026-05-12

## Overall Assessment: EXCELLENT

The animation system is production-grade fintech quality with comprehensive reduced-motion support.

## prefers-reduced-motion Compliance

**Status:** EXCELLENT — 20+ media queries across all CSS files + JS support.

Master override in `portal_tokens.css:236-247` sets all `--motion-*` and `--anim-duration-*` to 0ms.
Individual overrides in: components.css, portal.css, form.css, portal_ui_v2.css, command-palette.css.
count-up.js checks `prefersReducedMotion()` and shows final value instantly.

## Motion Token System

Centralized in `portal_tokens.css`:

| Token | Value | Usage |
|-------|-------|-------|
| `--motion-micro` | 100ms | Button clicks, icon toggles |
| `--motion-fast` | 100ms | Quick feedback |
| `--motion-normal` | 160ms | Standard transitions |
| `--motion-page` | 180ms | Page-level animations |
| `--motion-modal` | 250ms | Modals, toasts, overlays |
| `--motion-slow` | 300ms | Large-scale transitions |

Easing: `--ease-out` (snappy exit), `--ease-spring` (bouncy entrance), `--ease-smooth` (standard).

## Animation Inventory (11 keyframes)

| Keyframe | File | Purpose |
|----------|------|---------|
| `fadeSlideIn` | portal.css:982 | Row/card entrance |
| `scaleIn` | portal.css:987 | Scale 0.92→1 |
| `slideInRight` | portal.css:992 | Drawer slide |
| `toastIn` | components.css:741 | Toast entrance (spring) |
| `toastOut` | components.css:745 | Toast exit |
| `successCheckPop` | components.css:836 | Checkmark scale pop |
| `btnSpinner` | components.css:841 | Loading spinner |
| `btnLoadingPulse` | components.css:851 | Button opacity pulse |
| `successCheckDraw` | components.css:942 | SVG stroke draw |
| `modalScaleIn` | components.css:1002 | Modal scale+translate |
| `shimmer` | portal.css:1791 | Skeleton gradient sweep |

## Findings by Category

### Layout Shifts (CLS): MINIMAL RISK
- All animations use `transform` (GPU-accelerated, no reflow)
- Skeletons reserve explicit heights (46px rows, 72px cards)
- Toasts positioned `fixed` (no body layout impact)
- Progress bar uses `scaleX()` not width
- `will-change: transform` on cards

### Hover States: CONSISTENT
- 40+ hover states using unified transition timings
- All use specific property transitions (no `transition: all`)
- Pattern: `background`, `border-color`, `box-shadow`, `transform`

### Loading States: COMPREHENSIVE
- Button: `.btn--loading` with spinner + pulse animation
- Skeleton loaders: shimmer gradient (1.1s infinite)
- Page loading bar: 3px transform-based
- File upload: inline spinner + progress text
- JS helper: `uiMinSkeletonDelay(300ms)` prevents skeleton flash

### Toast System: POLISHED
- Spring entrance (200ms, `cubic-bezier(0.34, 1.56, 0.64, 1)`)
- Slide-right exit (150ms ease)
- TTL: success/info 3.2s, error 5s
- Max 3 visible toasts
- `aria-live="polite"` for screen readers

### count-up.js: GOOD (minor gap)
- Loaded on ALL portal pages via `base_portal.html:48`
- Used on 8+ pages with 250ms default duration
- **Gap:** `portal_dashboard_v2.html` uses static values instead of count-up
- Reduced-motion: shows final value instantly

### Skeleton Loaders: WELL IMPLEMENTED
- Shimmer with gradient sweep (1.1s)
- Reduced-motion fallback: solid 0.4 opacity (no animation)
- JS generators: `uiMakeSkeleton(rows, cols)` and `.cards(count)`
- Provider drawer has custom skeleton pulse

## Recommendations (Prioritized UX Wins)

| # | Recommendation | Effort | Impact |
|---|---------------|--------|--------|
| 1 | Add count-up to dashboard_v2 metrics | Low | Medium |
| 2 | Stagger animation should smoothly handle 9+ items | Low | Low |
| 3 | Verify 3px loading bar contrast in dark mode | Low | Low |
| 4 | Add button loading state to CFDI cancel button | Low | Medium |

## No Bugs Found

All animations are well-implemented with proper reduced-motion handling. No JS errors, no broken keyframes, no conflicting transitions detected.
