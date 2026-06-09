# Research: Portal Polish Fase 2 — Loading & navigation feedback

**Date:** 2026-06-09

## Key Finding: Most infrastructure already exists

### Item 7 — Top progress bar
- HTML: `#pageLoadingBar` and `#topProgress` in base_portal.html:298-299
- CSS: `.page-loading-bar` with `--active`/`--done` states (portal.css:2178-2212)
- CSS: `.top-progress` with `--active`/`--done` states (portal.css:2215-2242)
- JS: `uiPageLoadingStart()` / `uiPageLoadingStop()` in ui.js:902-923
- **Missing:** A script to wire link clicks → start bar, pageshow → stop bar

### Item 8 — Button loading on submit
- CSS: `.btn--loading` with spinner (portal.css:7164-7187)
- JS: `uiSetButtonLoading(btn, loading, loadingText)` in ui.js:134-142
- Settings forms at portal_settings.html use standard POST forms
- FIEL/CSD forms already use fetch-based submission
- **Missing:** Auto-wire for `data-loading-submit` forms

### Item 9 — Skeleton loaders
- CSS: `.skeleton`, `.skeleton--row-46`, `.skeleton--card-72` (portal.css:1897-1927)
- CSS: `.skeleton-line`, `.skeleton-card` (animations.css:177-220)
- JS: `uiGenerateSkeletonRows()`, `uiGenerateSkeletonCards()`, `uiMinSkeletonDelay()` (ui.js)
- Templates: portal_issued.html and portal_received.html ALREADY have 5 skeleton rows in tbody
- **Nothing missing — fully implemented**

## Scope
- Item 7: Create `portal_progress.js` (~40 lines) to wire navigation events
- Item 8: Add auto-wire for `data-loading-submit` + add attribute to 3 settings forms
- Item 9: Skip — already done
