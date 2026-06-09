/**
 * portal_progress.js — Wire navigation clicks to the top progress bar.
 *
 * Uses the existing uiPageLoadingStart/Stop from ui.js and the
 * .page-loading-bar CSS already in portal.css.
 */
(function () {
  'use strict';

  function hasLoadingApi() {
    return typeof window.uiPageLoadingStart === 'function' &&
           typeof window.uiPageLoadingStop === 'function';
  }

  function isSamePageNav(anchor) {
    if (anchor.host !== location.host) return false;
    if (anchor.pathname !== location.pathname) return false;
    if (anchor.search !== location.search && !anchor.hash) return false;
    return true;
  }

  function onClick(e) {
    if (!hasLoadingApi()) return;
    if (e.defaultPrevented) return;
    if (e.button !== 0) return;
    if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;

    var node = e.target;
    while (node && node !== document) {
      if (node.nodeType === 1 && node.tagName === 'A' && node.href) break;
      node = node.parentNode;
    }
    if (!node || node === document) return;

    var anchor = node;
    if (anchor.target && anchor.target !== '_self') return;
    if (anchor.hasAttribute('data-no-preload')) return;
    if (anchor.closest && anchor.closest('[data-no-preload]')) return;
    if (!/^https?:/.test(anchor.href)) return;
    if (anchor.origin !== location.origin) return;
    if (isSamePageNav(anchor)) return;

    window.uiPageLoadingStart();
  }

  // Complete bar when page is shown (including bfcache restores)
  window.addEventListener('pageshow', function () {
    if (hasLoadingApi()) window.uiPageLoadingStop();
  });

  document.addEventListener('click', onClick, true);
})();
