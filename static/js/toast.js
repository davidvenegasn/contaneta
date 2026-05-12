/**
 * Unified Toast Notification System.
 *
 * Provides showToast(message, type, duration) as the public API.
 * Auto-initializes by converting server-rendered flash messages
 * (elements with [data-flash-message]) into toasts.
 * Integrates with fetch/AJAX via window.toastFromResponse().
 *
 * Depends on: #toastStack container in the DOM (from base_portal.html).
 * CSS: static/css/toast.css
 */
(function () {
  'use strict';

  var TOAST_MAX_VISIBLE = 3;
  var DEFAULT_DURATION = 5000;
  var EXIT_ANIMATION_MS = 220;

  // Type aliases: normalize user-friendly names to internal CSS class names
  var TYPE_MAP = {
    success: 'success',
    error: 'danger',
    danger: 'danger',
    warning: 'warning',
    warn: 'warning',
    info: 'info'
  };

  // Default titles per type (Spanish, user-facing)
  var DEFAULT_TITLES = {
    success: 'Listo',
    danger: 'Error',
    warning: 'Aviso',
    info: 'Información'
  };

  // Default durations per type (ms)
  var TYPE_DURATIONS = {
    success: 3200,
    danger: 5000,
    warning: 4000,
    info: 4000
  };

  /**
   * Escape HTML to prevent XSS.
   * @param {string} s - Raw string.
   * @returns {string} Escaped HTML string.
   */
  function escapeHtml(s) {
    if (s == null) return '';
    var d = document.createElement('div');
    d.textContent = s;
    return d.innerHTML;
  }

  /**
   * Sanitize error messages: hide stack traces and overly long messages.
   * @param {string} msg - Raw error message.
   * @returns {string} Safe message for display.
   */
  function sanitizeErrorMessage(msg) {
    if (msg == null || typeof msg !== 'string') return 'Algo salió mal. Intenta de nuevo.';
    var s = String(msg).trim();
    if (s.length > 120) return 'Algo salió mal. Intenta de nuevo.';
    if (/^\s*at\s+/m.test(s) || /\n\s+at\s+/m.test(s)) return 'Algo salió mal. Intenta de nuevo.';
    return s;
  }

  /**
   * Get or create the toast stack container.
   * @returns {HTMLElement|null}
   */
  function getStack() {
    return document.getElementById('toastStack');
  }

  /**
   * Remove a toast element with exit animation.
   * @param {HTMLElement} el - The toast element.
   */
  function dismissToast(el) {
    if (!el || !el.parentNode) return;
    // Prevent double-dismiss
    if (el.getAttribute('data-dismissing') === '1') return;
    el.setAttribute('data-dismissing', '1');
    el.classList.add('toast--exiting');
    setTimeout(function () {
      if (el.parentNode) el.parentNode.removeChild(el);
    }, EXIT_ANIMATION_MS);
  }

  /**
   * Show a toast notification.
   *
   * @param {string} message - The message to display.
   * @param {string} [type='info'] - Toast type: 'success', 'error', 'danger', 'warning', 'info'.
   * @param {number} [duration=5000] - Auto-dismiss time in ms. Pass 0 to disable auto-dismiss.
   * @returns {HTMLElement} The toast element (for programmatic control).
   */
  function showToast(message, type, duration) {
    var stack = getStack();
    if (!stack) return null;

    var resolvedType = TYPE_MAP[type] || TYPE_MAP.info;
    var ttl = (typeof duration === 'number' && duration >= 0) ? duration : (TYPE_DURATIONS[resolvedType] || DEFAULT_DURATION);
    var title = DEFAULT_TITLES[resolvedType] || 'Info';

    // If message looks like a title (short, no period), use as title
    // If it has a colon, split into title:message
    var msg = '';
    if (typeof message === 'string' && message.indexOf(':') > 0 && message.indexOf(':') < 40) {
      var parts = message.split(':');
      title = parts[0].trim();
      msg = parts.slice(1).join(':').trim();
    } else {
      msg = message || '';
    }

    // Sanitize error messages
    if (resolvedType === 'danger' && msg) {
      msg = sanitizeErrorMessage(msg);
    }

    // Enforce max visible
    while (stack.children.length >= TOAST_MAX_VISIBLE) {
      stack.removeChild(stack.firstChild);
    }

    // Build DOM
    var el = document.createElement('div');
    el.className = 'toast toast--' + resolvedType;
    var isAssertive = resolvedType === 'danger';
    el.setAttribute('role', isAssertive ? 'alert' : 'status');
    el.setAttribute('aria-live', isAssertive ? 'assertive' : 'polite');

    var bodyHtml = '<div class="toast__body">' +
      '<p class="toast__title">' + escapeHtml(title) + '</p>' +
      (msg ? '<p class="toast__msg">' + escapeHtml(msg) + '</p>' : '') +
      '</div>';

    var closeHtml = '<button type="button" class="toast__close" aria-label="Cerrar">' +
      '<svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">' +
      '<path d="M11 3L3 11M3 3l8 8" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>' +
      '</svg></button>';

    var progressHtml = ttl > 0
      ? '<div class="toast__progress" style="animation:toastProgressShrink ' + ttl + 'ms linear forwards"></div>'
      : '';

    el.innerHTML = bodyHtml + closeHtml + progressHtml;

    // Close button handler
    var closeBtn = el.querySelector('.toast__close');
    if (closeBtn) {
      closeBtn.addEventListener('click', function () {
        dismissToast(el);
      });
    }

    stack.appendChild(el);

    // Auto-dismiss
    if (ttl > 0) {
      var timer = setTimeout(function () {
        dismissToast(el);
      }, ttl);
      // Store timer so close button can cancel it
      el._toastTimer = timer;
      // Override dismiss to also clear timer
      var origCloseHandler = closeBtn && closeBtn.onclick;
      if (closeBtn) {
        closeBtn.addEventListener('click', function () {
          clearTimeout(timer);
        });
      }
    }

    return el;
  }

  /**
   * Show a toast with full options (object API, compatible with portalToast).
   *
   * @param {Object} opts - Options.
   * @param {string} [opts.type='success'] - Toast type.
   * @param {string} [opts.title] - Title text.
   * @param {string} [opts.message] - Detail message.
   * @param {number} [opts.ttl] - Duration in ms.
   * @param {number} [opts.timeout] - Alias for ttl.
   * @returns {HTMLElement} The toast element.
   */
  function showToastOpts(opts) {
    var o = opts || {};
    var resolvedType = TYPE_MAP[o.type] || TYPE_MAP.success;
    var ttl = Number.isFinite(o.ttl) ? o.ttl : (Number.isFinite(o.timeout) ? o.timeout : (TYPE_DURATIONS[resolvedType] || DEFAULT_DURATION));
    var title = o.title || DEFAULT_TITLES[resolvedType] || 'Info';
    var msg = o.message || '';

    if (resolvedType === 'danger' && msg) {
      msg = sanitizeErrorMessage(msg);
    }

    var stack = getStack();
    if (!stack) return null;

    // Enforce max visible
    while (stack.children.length >= TOAST_MAX_VISIBLE) {
      stack.removeChild(stack.firstChild);
    }

    // Build DOM
    var el = document.createElement('div');
    el.className = 'toast toast--' + resolvedType;
    var isAssertive = resolvedType === 'danger';
    el.setAttribute('role', isAssertive ? 'alert' : 'status');
    el.setAttribute('aria-live', isAssertive ? 'assertive' : 'polite');

    var bodyHtml = '<div class="toast__body">' +
      '<p class="toast__title">' + escapeHtml(title) + '</p>' +
      (msg ? '<p class="toast__msg">' + escapeHtml(msg) + '</p>' : '') +
      '</div>';

    var closeHtml = '<button type="button" class="toast__close" aria-label="Cerrar">' +
      '<svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">' +
      '<path d="M11 3L3 11M3 3l8 8" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>' +
      '</svg></button>';

    var progressHtml = ttl > 0
      ? '<div class="toast__progress" style="animation:toastProgressShrink ' + ttl + 'ms linear forwards"></div>'
      : '';

    el.innerHTML = bodyHtml + closeHtml + progressHtml;

    // Close button handler
    var closeBtn = el.querySelector('.toast__close');
    if (closeBtn) {
      closeBtn.addEventListener('click', function () {
        dismissToast(el);
      });
    }

    stack.appendChild(el);

    // Auto-dismiss
    if (ttl > 0) {
      var timer = setTimeout(function () {
        dismissToast(el);
      }, ttl);
      el._toastTimer = timer;
      if (closeBtn) {
        closeBtn.addEventListener('click', function () {
          clearTimeout(timer);
        });
      }
    }

    return el;
  }

  /**
   * Convert server-rendered flash messages to toasts.
   * Looks for elements with [data-flash-message] attribute.
   * Expected markup: <div data-flash-message data-flash-type="success">Message text</div>
   */
  function convertFlashMessages() {
    var flashes = document.querySelectorAll('[data-flash-message]');
    for (var i = 0; i < flashes.length; i++) {
      var el = flashes[i];
      var type = el.getAttribute('data-flash-type') || 'info';
      var text = (el.textContent || '').trim();
      if (text) {
        showToast(text, type);
      }
      // Hide the original element
      el.style.display = 'none';
      el.setAttribute('aria-hidden', 'true');
    }
  }

  /**
   * Show a toast based on a fetch/AJAX JSON response.
   * Expects the standard API response format:
   *   { ok: true, data: ... } or { ok: false, error: { code, message }, ... }
   *
   * @param {Object} responseData - Parsed JSON response body.
   * @param {Object} [opts] - Options.
   * @param {string} [opts.successTitle] - Title for success toast.
   * @param {string} [opts.successMessage] - Message for success toast.
   * @param {string} [opts.errorTitle] - Title for error toast.
   * @returns {HTMLElement|null} The toast element, or null if no toast was shown.
   */
  function toastFromResponse(responseData, opts) {
    var o = opts || {};
    if (!responseData) {
      return showToast(o.errorTitle || 'Error: No se recibió respuesta del servidor.', 'error');
    }

    if (responseData.ok === true || responseData.ok === 'true') {
      var successMsg = o.successMessage || '';
      var successTitle = o.successTitle || 'Listo';
      return showToastOpts({
        type: 'success',
        title: successTitle,
        message: successMsg
      });
    }

    // Error response
    var errorMsg = '';
    if (responseData.error && typeof responseData.error.message === 'string') {
      errorMsg = responseData.error.message;
    } else if (typeof responseData.detail === 'string') {
      errorMsg = responseData.detail;
    } else if (Array.isArray(responseData.detail)) {
      errorMsg = responseData.detail.join('; ') || 'Error de validación';
    } else if (typeof responseData.message === 'string') {
      errorMsg = responseData.message;
    }

    return showToastOpts({
      type: 'danger',
      title: o.errorTitle || 'No pudimos completar la acción',
      message: errorMsg || 'Revisa los datos e intenta de nuevo.'
    });
  }

  // ===== Expose public API =====
  window.showToast = showToast;
  window.toastFromResponse = toastFromResponse;

  // Override portalToast to use the new unified system (backward compatible)
  window.portalToast = showToastOpts;

  // Shorthand API (override the one from ui.js if loaded later)
  window.toast = {
    success: function (msg) { return showToast(msg, 'success'); },
    error: function (msg) { return showToast(msg, 'error'); },
    warning: function (msg) { return showToast(msg, 'warning'); },
    info: function (msg) { return showToast(msg, 'info'); }
  };

  // Auto-initialize on DOMContentLoaded or immediately if already loaded
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', convertFlashMessages);
  } else {
    convertFlashMessages();
  }
})();
