/**
 * portal_uppercase.js — Auto-uppercase RFC and razón social inputs globally.
 *
 * SAT records RFC and legal_name in uppercase. Most fiscal validations match
 * exactly, so submitting lowercase values causes mismatch errors at timbrado.
 * This script transforms the input value to uppercase as the user types,
 * keeping the caret position stable.
 *
 * Triggers on:
 *  - name contains "rfc" (customer_rfc, issuer_rfc, supplier_rfc, etc.)
 *  - name contains "legal_name" or "razon_social"
 *  - explicit data-uppercase attribute (opt-in for other fields)
 *
 * Uses event delegation so it works for inputs added dynamically after page load
 * (e.g. modal openings, dynamic forms).
 */
(function () {
  'use strict';

  // Matches the inputs we want to auto-uppercase
  function shouldUppercase(el) {
    if (!el || el.tagName !== 'INPUT') return false;
    if (el.type === 'password' || el.type === 'email' || el.type === 'hidden') return false;
    if (el.hasAttribute('data-uppercase')) return true;
    if (el.hasAttribute('data-no-uppercase')) return false;
    var name = (el.name || '').toLowerCase();
    var id = (el.id || '').toLowerCase();
    var key = name + ' ' + id;
    return /(^|_|-)rfc(_|-|$)|rfc$/.test(key)
        || /legal_name|razon_social|razon-social|legalname/.test(key);
  }

  function toUpper(el) {
    var val = el.value;
    if (!val) return;
    var upper = val.toUpperCase();
    if (upper === val) return;
    // Preserve caret position across the value swap
    var start = el.selectionStart;
    var end = el.selectionEnd;
    el.value = upper;
    try {
      if (start !== null) el.setSelectionRange(start, end);
    } catch (_) { /* some input types don't support selection */ }
  }

  document.addEventListener('input', function (e) {
    if (shouldUppercase(e.target)) toUpper(e.target);
  }, true);

  // Also handle paste explicitly: the input event fires after paste, so the
  // listener above will catch it. But also normalize on blur as a safety net.
  document.addEventListener('blur', function (e) {
    if (shouldUppercase(e.target)) toUpper(e.target);
  }, true);

  // Apply to any pre-filled values on page load
  function applyToExisting() {
    var inputs = document.querySelectorAll('input');
    for (var i = 0; i < inputs.length; i++) {
      if (shouldUppercase(inputs[i])) toUpper(inputs[i]);
    }
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', applyToExisting);
  } else {
    applyToExisting();
  }
})();
