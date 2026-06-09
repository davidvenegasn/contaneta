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

  function findAnchor(target) {
    // e.target may be a Text node, Document, window, OR an SVG element inside
    // an anchor. Walk up manually to handle all cases robustly.
    var node = target;
    while (node) {
      if (node.nodeType === 1 && node.tagName && node.tagName.toUpperCase() === 'A' && node.getAttribute && node.getAttribute('href')) {
        return node;
      }
      node = node.parentNode || node.parentElement || null;
    }
    return null;
  }

  function onPointerOver(e) {
    var anchor = findAnchor(e.target);
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

  function onPointerOut(e) {
    var anchor = findAnchor(e.target);
    if (!anchor) return;
    if (anchor.href === pendingHref) {
      clearPending();
    }
  }

  function onTouchStart(e) {
    var anchor = findAnchor(e.target);
    if (!anchor || !shouldPreload(anchor)) return;
    prefetch(anchor.href);
  }

  // Click en el link de la página actual → no recargar. Usamos propiedades
  // directas del HTMLAnchorElement (no URL constructor) que el browser ya
  // resolvió. Match por pathname únicamente: si ya estás en /portal/facturas
  // y haces click en el link de Facturas (con o sin ?ym), no recargar.
  function isSamePageNav(anchor) {
    if (!anchor) return false;
    // anchor.host / anchor.pathname son propiedades del HTMLAnchorElement,
    // ya parseadas por el browser. Funcionan para clicks en SVG dentro del <a>.
    if (anchor.host !== location.host) return false;
    if (anchor.pathname !== location.pathname) return false;
    // Hash distinto = scroll a anchor diferente, permitir
    if (anchor.hash && anchor.hash !== location.hash) return false;
    return true;
  }

  function onClickIntercept(e) {
    if (e.defaultPrevented) return;
    if (e.button !== 0) return;
    if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    var anchor = findAnchor(e.target);
    if (!anchor) return;
    if (anchor.target && anchor.target !== '_self') return;
    if (!isSamePageNav(anchor)) return;
    e.preventDefault();
    e.stopPropagation();
  }

  // ── Rewrite sidebar/topbar links to monthPaths so they include stored YM ──
  // Without this, clicking a link to /portal/home triggers the early-head
  // script's location.replace() to inject ?ym=..., causing a double navigation
  // that breaks View Transitions and flashes the screen black.
  var MONTH_PATHS = [
    '/portal/home', '/portal/facturas', '/portal/movimientos',
    '/portal/bank/movements', '/portal/invoices-ext',
    '/portal/invoices/nomina', '/portal/month-close', '/portal/estados-financieros',
  ];

  function storedYm() {
    try {
      var m = document.querySelector('meta[name="portal-issuer-id"]');
      var id = m && m.getAttribute('content');
      var key = 'portal_selected_ym_' + (id || '0');
      var v = localStorage.getItem(key) || '';
      if (/^\d{4}-(0[1-9]|1[0-2])$/.test(v) || /^\d{4}$/.test(v)) return v;
    } catch (_) {}
    return '';
  }

  function injectYmIntoLinks() {
    var ym = storedYm();
    if (!ym) return;
    var anchors = document.querySelectorAll('a[href^="/portal/"]');
    for (var i = 0; i < anchors.length; i++) {
      var a = anchors[i];
      if (a.hasAttribute('data-no-ym-inject')) continue;
      var url;
      try { url = new URL(a.href); } catch (_) { continue; }
      if (MONTH_PATHS.indexOf(url.pathname) < 0) continue;
      if (url.searchParams.has('ym')) continue;
      url.searchParams.set('ym', ym);
      a.href = url.pathname + url.search + url.hash;
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', injectYmIntoLinks);
  } else {
    injectYmIntoLinks();
  }

  // ── Bind via event delegation on document (pointerover/out bubble naturally) ──
  document.addEventListener('pointerover', onPointerOver);
  document.addEventListener('pointerout', onPointerOut);
  document.addEventListener('touchstart', onTouchStart, { passive: true });
  document.addEventListener('click', onClickIntercept, true);
})();
