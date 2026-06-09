# Programmer Log: Portal Polish Fase 2 — Loading & navigation feedback

**Date:** 2026-06-09

## Key finding
Most infrastructure already existed (CSS, HTML elements, JS helpers). Only wiring was needed.

## Changes Made

### Item 7 — Top progress bar wiring
- NEW: `static/js/portal_progress.js` (~50 lines)
  - Click capture on same-origin `<a>` → calls `uiPageLoadingStart()`
  - `pageshow` event → calls `uiPageLoadingStop()`
  - Skips: same-page-nav, external, data-no-preload, modifier keys, non-left-click
  - Defensive: guards on `uiPageLoadingStart/Stop` existence

### Item 8 — Button loading auto-wire
- NEW: `static/js/portal_button_loading.js` (~35 lines)
  - On DOMContentLoaded, finds `form[data-loading-submit]` elements
  - On submit, finds submit button and calls `uiSetButtonLoading(btn, true, text)`
  - Loading text comes from `data-loading-submit` attribute value
- EDIT: `templates/portal_settings.html` — added `data-loading-submit="Guardando…"` to 3 forms:
  - Profile form (line 48)
  - Password form (line 72)
  - Issuer form (line 121)

### Item 9 — Skeleton loaders
- SKIPPED — already fully implemented (CSS + templates + JS helpers)

### Wiring
- EDIT: `templates/base_portal.html` — added 2 `<script defer>` tags after portal_preload.js

## Test Results
- 879 passed, 3 failed (pre-existing FIEL badge), 4 skipped
- 0 new failures
