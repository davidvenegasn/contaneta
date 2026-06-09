/**
 * portal_form_drafts.js — Auto-save form field data to localStorage.
 *
 * Forms with `data-draft="<form-id>"` will auto-save their input values
 * on change. On page load, if a draft exists (< 24h old), a recovery
 * banner is shown above the form.
 *
 * Excluded fields: password, csrf_token, file inputs, hidden inputs.
 */
(function () {
  'use strict';

  var MAX_AGE_MS = 86400000; // 24 hours
  var DEBOUNCE_MS = 500;
  var EXCLUDED_NAMES = ['csrf_token', 'csrfmiddlewaretoken'];

  function issuerId() {
    var m = document.querySelector('meta[name="portal-issuer-id"]');
    return (m && m.getAttribute('content')) || '0';
  }

  function draftKey(formId) {
    return 'portal_draft_' + formId + '_' + issuerId();
  }

  function shouldSaveField(input) {
    if (!input.name) return false;
    if (input.type === 'password' || input.type === 'file' || input.type === 'hidden') return false;
    if (EXCLUDED_NAMES.indexOf(input.name) >= 0) return false;
    return true;
  }

  function collectFormData(form) {
    var data = {};
    var inputs = form.querySelectorAll('input, textarea, select');
    for (var i = 0; i < inputs.length; i++) {
      var input = inputs[i];
      if (!shouldSaveField(input)) continue;
      if (input.type === 'checkbox' || input.type === 'radio') {
        data[input.name] = input.checked;
      } else {
        data[input.name] = input.value;
      }
    }
    return data;
  }

  function restoreFormData(form, data) {
    var inputs = form.querySelectorAll('input, textarea, select');
    for (var i = 0; i < inputs.length; i++) {
      var input = inputs[i];
      if (!shouldSaveField(input)) continue;
      if (!(input.name in data)) continue;
      if (input.type === 'checkbox' || input.type === 'radio') {
        input.checked = !!data[input.name];
      } else {
        input.value = data[input.name];
        // Trigger change so any dependent UI updates
        input.dispatchEvent(new Event('change', { bubbles: true }));
      }
    }
  }

  function saveDraft(formId, form) {
    var data = collectFormData(form);
    // Don't save if all fields are empty
    var hasContent = false;
    for (var key in data) {
      if (data[key] && data[key] !== false) { hasContent = true; break; }
    }
    if (!hasContent) return;
    try {
      localStorage.setItem(draftKey(formId), JSON.stringify({
        data: data,
        ts: Date.now()
      }));
    } catch (e) {}
  }

  function loadDraft(formId) {
    try {
      var raw = localStorage.getItem(draftKey(formId));
      if (!raw) return null;
      var draft = JSON.parse(raw);
      if (Date.now() - draft.ts > MAX_AGE_MS) {
        localStorage.removeItem(draftKey(formId));
        return null;
      }
      return draft;
    } catch (e) { return null; }
  }

  function clearDraft(formId) {
    try { localStorage.removeItem(draftKey(formId)); } catch (e) {}
  }

  function relativeTime(ts) {
    var diff = Date.now() - ts;
    var min = Math.floor(diff / 60000);
    if (min < 1) return 'hace unos segundos';
    if (min < 60) return 'hace ' + min + ' min';
    var hrs = Math.floor(min / 60);
    if (hrs < 24) return 'hace ' + hrs + (hrs === 1 ? ' hora' : ' horas');
    return 'ayer';
  }

  function createBanner(form, formId, draft) {
    var banner = document.createElement('div');
    banner.className = 'draft-banner';
    banner.setAttribute('role', 'status');
    banner.innerHTML =
      '<span class="draft-banner__text">' +
        'Borrador guardado ' + relativeTime(draft.ts) +
      '</span>' +
      '<button type="button" class="draft-banner__btn draft-banner__btn--restore">Recuperar</button>' +
      '<button type="button" class="draft-banner__btn draft-banner__btn--discard">Descartar</button>';

    var restoreBtn = banner.querySelector('.draft-banner__btn--restore');
    var discardBtn = banner.querySelector('.draft-banner__btn--discard');

    restoreBtn.addEventListener('click', function () {
      restoreFormData(form, draft.data);
      banner.remove();
    });

    discardBtn.addEventListener('click', function () {
      clearDraft(formId);
      banner.remove();
    });

    form.parentNode.insertBefore(banner, form);
  }

  function initForm(form) {
    var formId = form.getAttribute('data-draft');
    if (!formId) return;

    // Check for existing draft
    var draft = loadDraft(formId);
    if (draft) {
      createBanner(form, formId, draft);
    }

    // Auto-save on input (debounced)
    var timer = null;
    form.addEventListener('input', function () {
      if (timer) clearTimeout(timer);
      timer = setTimeout(function () {
        saveDraft(formId, form);
      }, DEBOUNCE_MS);
    });

    // Clear draft on successful submit
    form.addEventListener('submit', function () {
      clearDraft(formId);
    });
  }

  function init() {
    var forms = document.querySelectorAll('form[data-draft]');
    for (var i = 0; i < forms.length; i++) {
      initForm(forms[i]);
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
