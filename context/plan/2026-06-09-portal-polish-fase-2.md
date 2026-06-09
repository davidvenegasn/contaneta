# Plan: Portal Polish Fase 2 — Loading & navigation feedback

**Date:** 2026-06-09

## Item 7 — Top progress bar wiring
**New file:** `static/js/portal_progress.js` (defer)

Logic:
- On `click` capture: if same-origin `<a>` that isn't same-page-nav and not `data-no-preload`, call `uiPageLoadingStart()`
- On `pageshow`: call `uiPageLoadingStop()`
- On `pagehide`: reset bar
- Guard: skip if `uiPageLoadingStart` not defined (defensive)
- No new CSS needed — existing `.page-loading-bar` styles are complete

**Wire in:** `templates/base_portal.html` — add `<script defer>` after portal_preload.js

## Item 8 — Button loading auto-wire
**New file:** `static/js/portal_button_loading.js` (defer)

Logic:
- On DOMContentLoaded, find all `form[data-loading-submit]`
- On `submit` event, find the submit button, call `uiSetButtonLoading(btn, true)`
- Guard: skip if `uiSetButtonLoading` not defined

**Template changes:**
- `portal_settings.html`: Add `data-loading-submit` to profile, password, issuer forms

**Wire in:** `templates/base_portal.html` — add `<script defer>`

## Item 9 — Skeleton loaders
**SKIP** — already fully implemented in templates and CSS.

## Files touched
1. NEW: `static/js/portal_progress.js`
2. NEW: `static/js/portal_button_loading.js`
3. EDIT: `templates/base_portal.html` (2 script tags)
4. EDIT: `templates/portal_settings.html` (3 data attributes)
