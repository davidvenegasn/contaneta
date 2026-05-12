# Bank Movements: Scroll-to-Top Bug Investigation

**Date:** 2026-05-12
**Status:** Inconclusive — no clear root cause found in code

## Symptom

Clicking on certain elements in `/portal/bank/movements` causes the page to scroll to the top unexpectedly.

## Investigation

### Files examined

- `templates/portal_bank_movements.html` — full JS section (lines 380-544)
- `templates/base_portal.html` — global event listeners
- `static/js/ui.js` — scroll-lock mechanism, global handlers

### Ruled out

1. **No `href="#"`** — no anchor links with empty fragment. All `<a>` tags have real hrefs.
2. **No `scrollTo`/`scrollIntoView`** in bank movements JS — only `window.scrollTo` exists in `ui.js:uiUnlockScroll()`.
3. **No `location.reload()`** in normal click handlers — only in delete-all and file-upload success callbacks.
4. **No `location.hash`** manipulation.
5. **Click handlers use `<td>` elements**, not `<a>` — clicking category/concept cells directly, no navigation.

### Likely causes (hypotheses)

1. **`select.click()` on line 452** — after dynamically inserting a `<select>` into the category cell, `setTimeout(() => select.click(), 0)` programmatically triggers the dropdown. Some browsers scroll to bring the focused/opened `<select>` into view. This is native browser behavior and hard to prevent.

2. **`uiUnlockScroll()` in `ui.js:18-25`** — when a modal/overlay closes, it restores scroll position via `window.scrollTo(0, parseInt(scrollY) * -1)`. If `document.body.style.top` was cleared before reading, `scrollY` would be `'0'` or empty, scrolling to top. This could happen if `uiLockScroll`/`uiUnlockScroll` calls are mismatched (e.g., lock called once, unlock called twice).

3. **Create panel interaction** — the "Nueva" FAB/button opens a create panel overlay. If this uses `uiLockScroll` but the dismiss handler calls `uiUnlockScroll` with a stale `body.style.top`, scroll restores to 0.

### Recommended next steps

- Add `console.log` to `uiUnlockScroll` to trace when it fires and what `scrollY` value it restores
- Test in browser dev tools: monitor scroll events with `window.addEventListener('scroll', e => console.trace('scroll'))` to identify the call stack
- Check if the bug is specific to the category dropdown click (hypothesis 1) vs. closing overlays (hypothesis 2/3)
