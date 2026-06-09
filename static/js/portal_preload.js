/**
 * portal_preload.js — Link preloading on hover/touchstart.
 *
 * Injects <link rel="prefetch"> for same-origin portal links when the user
 * hovers (or touches) them, so the browser pre-fetches the next page before
 * click. Combined with View Transitions API CSS, this gives near-instant
 * page loads without any framework (htmx, Turbo, etc.).
 *
 * Constraints:
 *  - 65 ms debounce (avoids drive-by hovers)
 *  - Max 4 concurrent prefetches
 *  - LRU set prevents duplicate fetches
 *  - Respects Save-Data header and slow connections
 *  - Skips links with [data-no-preload], external links, hash-only links,
 *    non-GET actions (#, javascript:, mailto:, tel:)
 */
(function () {
  'use strict';

  // ── Guards ──
  var conn = navigator.connection || navigator.mozConnection || navigator.webkitConnection;
  if (conn && conn.saveData) return;
  if (conn && conn.effectiveType && /2g|slow-2g/.test(conn.effectiveType)) return;

  var MAX_CONCURRENT = 4;
  var MAX_CACHE = 50;
  var DEBOUNCE_MS = 65;

  var active = 0;
  var cache = [];       // LRU list of prefetched URLs
  var pending = null;   // debounce timer ID
  var pendingHref = ''; // href being debounced

  function shouldPreload(anchor) {
    if (!anchor || !anchor.href) return false;
    if (anchor.hasAttribute('data-no-preload')) return false;
    if (anchor.closest('[data-no-preload]')) return false;

    var href = anchor.href;
    // Skip non-http, hash-only, javascript:, mailto:, tel:
    if (!/^https?:/.test(href)) return false;
    // Same origin only
    if (anchor.origin !== location.origin) return false;
    // Skip if target opens new tab
    if (anchor.target && anchor.target !== '_self') return false;
    // Skip current page
    if (href === location.href) return false;
    // Skip anchors pointing to same page with different hash
    if (anchor.pathname === location.pathname && anchor.search === location.search && anchor.hash) return false;

    return true;
  }

  function alreadyCached(href) {
    return cache.indexOf(href) !== -1;
  }

  function addToCache(href) {
    // LRU: remove if already present, push to end
    var idx = cache.indexOf(href);
    if (idx !== -1) cache.splice(idx, 1);
    cache.push(href);
    // Evict oldest if over limit
    while (cache.length > MAX_CACHE) cache.shift();
  }

  function prefetch(href) {
    if (alreadyCached(href)) return;
    if (active >= MAX_CONCURRENT) return;

    addToCache(href);
    active++;

    var link = document.createElement('link');
    link.rel = 'prefetch';
    link.href = href;
    link.as = 'document';

    link.onload = link.onerror = function () {
      active--;
    };

    document.head.appendChild(link);
  }

  function clearPending() {
    if (pending) {
      clearTimeout(pending);
      pending = null;
      pendingHref = '';
    }
  }

  function onPointerEnter(e) {
    var anchor = e.target.closest('a[href]');
    if (!anchor || !shouldPreload(anchor)) return;

    var href = anchor.href;
    if (alreadyCached(href)) return;

    clearPending();
    pendingHref = href;
    pending = setTimeout(function () {
      pending = null;
      prefetch(href);
    }, DEBOUNCE_MS);
  }

  function onPointerLeave(e) {
    var anchor = e.target.closest('a[href]');
    if (!anchor) return;
    if (anchor.href === pendingHref) {
      clearPending();
    }
  }

  function onTouchStart(e) {
    var anchor = e.target.closest('a[href]');
    if (!anchor || !shouldPreload(anchor)) return;
    // Touchstart: prefetch immediately (no debounce — touch implies intent)
    prefetch(anchor.href);
  }

  // ── Bind via event delegation on document ──
  document.addEventListener('pointerenter', onPointerEnter, true);
  document.addEventListener('pointerleave', onPointerLeave, true);
  document.addEventListener('touchstart', onTouchStart, { passive: true, capture: true });
})();
