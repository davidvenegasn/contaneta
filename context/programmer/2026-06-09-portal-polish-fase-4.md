# Programmer Log: Portal Polish Fase 4 — State persistence & resilience

**Date:** 2026-06-09

## Changes Made

### Item 13 — Scroll position restoration
- NEW: `static/js/portal_scroll_restore.js` (~70 lines)
  - Sets `history.scrollRestoration = 'manual'`
  - Saves `{ y, ts }` to sessionStorage on `beforeunload`/`pagehide`
  - Restores scroll via rAF on DOMContentLoaded
  - 1-hour TTL, skips trivial positions (< 10px)
  - Periodic cleanup of expired entries

### Item 14 — Form drafts in localStorage
- NEW: `static/js/portal_form_drafts.js` (~150 lines)
  - Auto-saves `form[data-draft]` input values on change (500ms debounce)
  - Key: `portal_draft_<formId>_<issuerId>` (tenant-scoped)
  - Excludes: password, file, hidden, csrf_token fields
  - Shows recovery banner: "Borrador guardado hace X min" [Recuperar] [Descartar]
  - Clears draft on successful submit
  - 24-hour TTL
- NEW CSS: `.draft-banner` styles (portal.css section 18) with nightmode support
- EDIT: `portal_settings.html` — added `data-draft="settings-profile"` and `data-draft="settings-issuer"` (password form excluded — sensitive)

### Item 15 — Error boundary
- SKIPPED — already fully implemented:
  - 500/404/403 error pages exist
  - Error events logged to DB with redaction
  - Request ID tracked via ContextVar
  - Admin dashboard for error review

### Wiring
- EDIT: `base_portal.html` — added 2 `<script defer>` tags

## Test Results
- 879 passed, 3 failed (pre-existing FIEL badge), 4 skipped
- 0 new failures
