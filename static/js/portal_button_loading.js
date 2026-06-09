/**
 * portal_button_loading.js — Auto-wire loading state on form submit buttons.
 *
 * Forms with `data-loading-submit` will show a spinner on their submit
 * button when submitted. Uses the existing uiSetButtonLoading() from ui.js.
 */
(function () {
  'use strict';

  function init() {
    if (typeof window.uiSetButtonLoading !== 'function') return;

    var forms = document.querySelectorAll('form[data-loading-submit]');
    for (var i = 0; i < forms.length; i++) {
      forms[i].addEventListener('submit', onSubmit);
    }
  }

  function onSubmit(e) {
    var form = e.currentTarget;
    var btn = form.querySelector('button[type="submit"], input[type="submit"]');
    if (!btn) return;
    if (btn.disabled) return;

    var loadingText = form.getAttribute('data-loading-submit') || 'Procesando\u2026';
    window.uiSetButtonLoading(btn, true, loadingText);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
