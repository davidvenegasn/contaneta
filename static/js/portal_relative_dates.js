/**
 * portal_relative_dates.js — Progressive relative date enhancement.
 *
 * Scans for <time datetime="..."> elements and replaces their text content
 * with a human-readable relative date ("Hace 3 min", "Ayer", "Hace 2 días").
 * The original absolute date is preserved in the title attribute for hover.
 *
 * Re-scans every 60s if the page has focus, so "Hace 2 min" becomes "Hace 3 min".
 * Locale: es-MX.
 */
(function () {
  'use strict';

  var REFRESH_INTERVAL = 60000; // 60s
  var MAX_RELATIVE_DAYS = 30;
  var refreshTimer = null;

  // Intl.RelativeTimeFormat for Spanish
  var rtf = null;
  try {
    rtf = new Intl.RelativeTimeFormat('es-MX', { numeric: 'auto', style: 'long' });
  } catch (e) {
    // Browser doesn't support RelativeTimeFormat — skip enhancement
    return;
  }

  var dtfAbsolute = null;
  try {
    dtfAbsolute = new Intl.DateTimeFormat('es-MX', {
      day: 'numeric', month: 'short', year: 'numeric',
      hour: '2-digit', minute: '2-digit', hour12: false
    });
  } catch (e) {
    // Fallback: no title attribute formatting
  }

  var dtfShort = null;
  try {
    dtfShort = new Intl.DateTimeFormat('es-MX', {
      day: 'numeric', month: 'short', year: 'numeric'
    });
  } catch (e) {}

  function relativeText(date) {
    var now = Date.now();
    var diff = now - date.getTime();
    var absSec = Math.abs(diff) / 1000;

    if (absSec < 60) return 'Justo ahora';

    var absMin = Math.floor(absSec / 60);
    if (absMin < 60) return rtf.format(-absMin, 'minute');

    var absHour = Math.floor(absMin / 60);
    if (absHour < 24) return rtf.format(-absHour, 'hour');

    var absDay = Math.floor(absHour / 24);
    if (absDay <= MAX_RELATIVE_DAYS) return rtf.format(-absDay, 'day');

    // Beyond 30 days: show short absolute date
    return dtfShort ? dtfShort.format(date) : date.toLocaleDateString('es-MX');
  }

  function absoluteTitle(date) {
    return dtfAbsolute ? dtfAbsolute.format(date) : date.toLocaleString('es-MX');
  }

  function processElements() {
    var elements = document.querySelectorAll('time[datetime]');
    for (var i = 0; i < elements.length; i++) {
      var el = elements[i];
      var raw = el.getAttribute('datetime');
      if (!raw) continue;

      var date = new Date(raw);
      if (isNaN(date.getTime())) continue;

      var text = relativeText(date);
      el.textContent = text;

      // Set title for hover tooltip with full absolute date
      if (!el.hasAttribute('data-rel-no-title')) {
        el.setAttribute('title', absoluteTitle(date));
      }

      // Mark as processed
      el.setAttribute('data-rel-processed', '1');
    }
  }

  function startRefresh() {
    if (refreshTimer) return;
    refreshTimer = setInterval(function () {
      if (document.hasFocus()) processElements();
    }, REFRESH_INTERVAL);
  }

  function init() {
    processElements();
    startRefresh();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  // Also re-process after dynamic content loads (MutationObserver is overkill;
  // expose a global so other scripts can call it after DOM updates)
  window.portalRelativeDatesRefresh = processElements;
})();
