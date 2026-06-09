# Programmer Log: View Transitions API + Link Preloading on Hover

**Date:** 2026-06-09

## Context
The htmx SPA navigation experiment (commit c1ef97b) was reverted (commit 080cf53) due to CSP blocks, null bugs, dead @import, and page-enter CSS conflict. This is the replacement: a non-invasive, zero-framework approach using native browser APIs.

## Changes Made

### 1. `static/css/portal.css` — View Transitions CSS
- Added `@view-transition { navigation: auto; }` at-rule (section 17)
- Custom keyframes: `portal-vt-fade-out` (140ms) and `portal-vt-fade-in` (180ms, 60ms delay)
- `::view-transition-old(root)` and `::view-transition-new(root)` pseudo-element animations
- `prefers-reduced-motion: reduce` disables all view transition animations

### 2. `static/js/portal_preload.js` — NEW (~3KB)
- Hover-triggered `<link rel="prefetch">` injection via event delegation
- 65ms debounce on `pointerenter` (avoids drive-by hovers)
- Instant prefetch on `touchstart` (touch = intent)
- Max 4 concurrent prefetches, LRU cache of 50 URLs
- Skips: `data-no-preload` links, external origins, hash-only, javascript:, mailto:, tel:
- Respects `Save-Data` header and `effectiveType` (2g/slow-2g → disabled)
- Checks `anchor.target` to skip _blank links

### 3. `templates/base_portal.html` — Wiring
- Added `<script defer src="/static/js/portal_preload.js">` before fonts
- Added `data-no-preload` to logout form

### 4. `tests/test_portal_preload.py` — NEW (6 tests)
- Script exists
- Referenced in base template with `defer`
- View Transitions CSS present
- Reduced-motion disables transitions
- Logout has `data-no-preload`
- Script checks Save-Data / effectiveType

## Test Results
- 880 passed, 3 failed (pre-existing FIEL badge tests), 4 skipped
- 0 new failures
