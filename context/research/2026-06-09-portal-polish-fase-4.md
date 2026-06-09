# Research: Portal Polish Fase 4 — State persistence & resilience

**Date:** 2026-06-09

## Item 13 — Scroll position restoration
- `history.scrollRestoration` NOT used anywhere
- ui.js has manual scroll tracking for modal overlays only
- portal_preload.js has no scroll-related code
- **Needs implementation**

## Item 14 — Form drafts in localStorage
- No `data-draft` attributes in any templates
- No form auto-save functionality exists
- localStorage used only for UI state (drawer, collapse, ym)
- **Needs implementation**

## Item 15 — Error boundary
- **ALREADY FULLY IMPLEMENTED:**
  - `@app.exception_handler(500)` → renders `errors/500.html` with request_id
  - `@app.exception_handler(404)` → renders `errors/404.html`
  - `@app.exception_handler(403)` → renders `errors/403.html`
  - `@app.exception_handler(AppError)` → custom error with request_id
  - SQLite, subprocess handlers also present
  - Error events logged to DB with redaction
  - Admin dashboard for error review
  - Request ID via ContextVar + request.state
- **SKIP — nothing to add**

## Scope
- Item 13: Create `portal_scroll_restore.js` (~40 lines)
- Item 14: Create `portal_form_drafts.js` (~60 lines), add `data-draft` to create forms
- Item 15: Skip — already comprehensive
