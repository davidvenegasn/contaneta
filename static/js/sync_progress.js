/**
 * sync_progress.js — Polls /api/sync/progress and updates the dashboard banner.
 * Shows when SAT sync is active, hides when done. Auto-stops after 10 min.
 */
(function() {
  var banner = document.getElementById('syncProgressBanner');
  if (!banner) return;

  var textEl = document.getElementById('syncBannerText');
  var detailEl = document.getElementById('syncBannerDetail');
  var spinnerEl = document.getElementById('syncSpinner');
  var dismissBtn = document.getElementById('syncBannerDismiss');
  var timer = null;
  var dismissed = false;
  var pollStart = Date.now();
  var MAX_POLL_MS = 10 * 60 * 1000; // 10 minutes

  if (dismissBtn) {
    dismissBtn.addEventListener('click', function() {
      banner.hidden = true;
      dismissed = true;
      if (timer) clearTimeout(timer);
    });
  }

  function update(data) {
    var d = data.data || data;
    if (dismissed) return;

    if (d.syncing) {
      banner.hidden = false;
      if (textEl) textEl.textContent = 'Sincronizando facturas del SAT\u2026';
      if (detailEl) {
        var parts = [];
        if (d.active > 0) parts.push(d.active + ' en proceso');
        if (d.done > 0) parts.push(d.done + ' completado' + (d.done > 1 ? 's' : ''));
        detailEl.textContent = parts.join(' \u00b7 ') || '';
      }
      if (spinnerEl) spinnerEl.hidden = false;
    } else if (d.done > 0 && !d.syncing) {
      // Sync just finished — show briefly then hide
      banner.hidden = false;
      if (textEl) textEl.textContent = 'Sincronizaci\u00f3n completada';
      if (detailEl) detailEl.textContent = d.done + ' tarea' + (d.done > 1 ? 's' : '') + ' completada' + (d.done > 1 ? 's' : '');
      if (spinnerEl) spinnerEl.hidden = true;
      banner.style.borderLeftColor = 'var(--success, #16a34a)';
      banner.style.background = 'var(--success-bg, rgba(22,163,74,.08))';
      if (textEl) textEl.style.color = 'var(--success, #16a34a)';
      setTimeout(function() { if (!dismissed) banner.hidden = true; }, 8000);
      return; // stop polling
    } else {
      banner.hidden = true;
      return; // nothing to show
    }

    // Continue polling if still syncing and within time limit
    if (Date.now() - pollStart < MAX_POLL_MS) {
      timer = setTimeout(poll, 5000);
    }
  }

  function poll() {
    var fetchFn = window.portalFetchJSON || function(url) {
      return fetch(url, { credentials: 'same-origin' }).then(function(r) {
        return r.json().then(function(d) { return { data: d }; });
      });
    };
    fetchFn('/api/sync/progress')
      .then(function(r) { update(r.data || r); })
      .catch(function() { /* silent */ });
  }

  // Initial poll
  poll();
})();
