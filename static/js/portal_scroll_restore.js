/**
 * portal_scroll_restore.js — Restore scroll position on back/forward navigation.
 *
 * Saves scroll position in sessionStorage before leaving a page and restores
 * it on return. Entries expire after 1 hour to prevent stale positions.
 */
(function () {
  'use strict';

  var MAX_AGE_MS = 3600000; // 1 hour
  var PREFIX = 'portal_scroll_';

  history.scrollRestoration = 'manual';

  function storageKey() {
    return PREFIX + location.pathname + location.search;
  }

  function save() {
    var y = window.scrollY || window.pageYOffset || 0;
    if (y < 10) return; // Don't save trivial scroll positions
    try {
      sessionStorage.setItem(storageKey(), JSON.stringify({
        y: y,
        ts: Date.now()
      }));
    } catch (e) { /* quota exceeded or private browsing */ }
  }

  function restore() {
    try {
      var raw = sessionStorage.getItem(storageKey());
      if (!raw) return;
      var data = JSON.parse(raw);
      if (Date.now() - data.ts > MAX_AGE_MS) {
        sessionStorage.removeItem(storageKey());
        return;
      }
      // Restore after a rAF to ensure DOM is laid out
      requestAnimationFrame(function () {
        window.scrollTo(0, data.y);
      });
    } catch (e) { /* parse error or no access */ }
  }

  function cleanup() {
    try {
      var now = Date.now();
      for (var i = sessionStorage.length - 1; i >= 0; i--) {
        var key = sessionStorage.key(i);
        if (!key || key.indexOf(PREFIX) !== 0) continue;
        try {
          var data = JSON.parse(sessionStorage.getItem(key));
          if (now - data.ts > MAX_AGE_MS) sessionStorage.removeItem(key);
        } catch (e) { sessionStorage.removeItem(key); }
      }
    } catch (e) {}
  }

  // Save before leaving
  window.addEventListener('beforeunload', save);
  window.addEventListener('pagehide', save);

  // Restore on load
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', restore);
  } else {
    restore();
  }

  // Periodic cleanup (don't block init)
  setTimeout(cleanup, 5000);
})();
