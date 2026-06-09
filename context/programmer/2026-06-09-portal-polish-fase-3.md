# Programmer Log: Portal Polish Fase 3 — Smart content

**Date:** 2026-06-09

## Key finding
2 of 3 items already fully implemented. Only relative dates needed work.

## Changes Made

### Item 10 — Relative dates
- NEW: `static/js/portal_relative_dates.js` (~100 lines)
  - Uses `Intl.RelativeTimeFormat('es-MX')` for localized relative text
  - Scans `<time datetime="...">` elements, replaces with "Hace X min/horas/días"
  - Sets `title` attribute with full absolute date for hover tooltip
  - Refreshes every 60s when page has focus
  - Falls back gracefully if Intl not supported
  - Exposes `window.portalRelativeDatesRefresh()` for dynamic content
  - Beyond 30 days: shows short absolute date ("15 mar 2026")
- EDIT: `templates/base_portal.html` — added `<script defer>` tag
- EDIT: `templates/portal_clients.html` — wrapped `last_seen_at` in `<time>` tag

### Item 11 — Keyboard shortcuts
- SKIPPED — already fully implemented:
  - G+H/M/F/C/Q/S chord navigation
  - N for new invoice
  - ? for help modal with all shortcuts listed
  - `/` for command palette (via Cmd+K)
  - Input focus detection, command palette awareness

### Item 12 — Empty states
- SKIPPED — already fully implemented:
  - Jinja2 macro `portal_empty_state` with 7 icon types
  - Used in clients, products, issued_list, received_list
  - CTA buttons included in each empty state

## Test Results
- 879 passed, 3 failed (pre-existing FIEL badge), 4 skipped
- 0 new failures
