/**
 * UI micro-interactions: toasts, loading buttons, success overlay.
 * Sin frameworks. Requiere portalToast definido en base_portal (antes de cargar este script).
 */

(function () {
  'use strict';

  var escapeHtml = function (s) {
    if (s == null) return '';
    var d = document.createElement('div');
    d.textContent = s;
    return d.innerHTML;
  };

  /**
   * P39: Resalta en HTML las coincidencias de query en text (case-insensitive). Uso en búsqueda clientes/productos/proveedores.
   * @param {string} text - texto a mostrar
   * @param {string} query - término de búsqueda (se envuelve en <mark class="search-highlight">)
   * @returns {string} HTML seguro con marcas
   */
  window.uiHighlightSearch = function (text, query) {
    if (text == null) return '';
    var s = String(text);
    if (!query || !String(query).trim()) return escapeHtml(s);
    var q = String(query).trim();
    var lower = s.toLowerCase();
    var qLower = q.toLowerCase();
    var out = '';
    var pos = 0;
    var i;
    while ((i = lower.indexOf(qLower, pos)) !== -1) {
      out += escapeHtml(s.slice(pos, i)) + '<mark class="search-highlight">' + escapeHtml(s.slice(i, i + q.length)) + '</mark>';
      pos = i + q.length;
    }
    out += escapeHtml(s.slice(pos));
    return out;
  };

  /**
   * API global: window.uiToast({ type, title, message, timeout })
   * type: 'success' | 'error' | 'danger' | 'info' | 'warning'
   * timeout: ms (opcional; por defecto 3200, error 5000)
   */
  window.uiToast = function (opts) {
    if (!opts || typeof opts !== 'object') return;
    var o = {
      type: opts.type === 'error' ? 'danger' : (opts.type || 'success'),
      title: opts.title || (opts.type === 'danger' || opts.type === 'error' ? 'Error' : 'Listo'),
      message: opts.message || '',
      ttl: Number.isFinite(opts.timeout) ? opts.timeout : (opts.type === 'danger' || opts.type === 'error' ? 5000 : 3200)
    };
    if (window.portalToast) window.portalToast(o);
  };

  /**
   * P37: Modal de confirmación reutilizable (sin alert/confirm nativo).
   * Uso: const ok = await uiConfirm({ title, message, confirmText, cancelText });
   * @param {Object} opts - { title, message, confirmText, cancelText }
   * @returns {Promise<boolean>} true si confirmó, false si canceló
   */
  window.uiConfirm = function (opts) {
    var o = opts || {};
    if (typeof window.portalConfirm === 'function') {
      return window.portalConfirm({
        title: o.title || 'Confirmar',
        message: o.message || '¿Continuar?',
        confirmLabel: o.confirmText || o.confirmLabel || 'Confirmar',
        cancelLabel: o.cancelText || o.cancelLabel || 'Cancelar',
      });
    }
    return Promise.resolve(!!window.confirm((o.message || '¿Continuar?') + '\n\n(Usa el portal para confirmaciones con estilo.)'));
  };

  /**
   * Muestra toast de error. Uso: uiToastError(err, 'Título', 'Mensaje por defecto')
   */
  window.uiToastError = function (err, title, message) {
    var msg = err && (err.message || err.detail || (typeof err === 'string' ? err : null));
    window.uiToast({
      type: 'danger',
      title: title || 'Error',
      message: msg || message || 'No se pudo completar la acción.',
      timeout: 5000
    });
  };

  /**
   * P25: Toast unificado (feedback consistente tipo fintech).
   * API: toast.success(msg) | toast.error(msg) | toast.info(msg)
   * Usa #toastStack en base_portal; animación in/out; máximo 3 visibles.
   * No usar para carga de listas (empty/error => bloque en página).
   */
  window.toast = {
    success: function (msg) {
      if (window.portalToast) window.portalToast({ type: 'success', title: msg || 'Listo' });
    },
    error: function (msg) {
      if (window.portalToast) window.portalToast({ type: 'danger', title: msg || 'Error', ttl: 5000 });
    },
    info: function (msg) {
      if (window.portalToast) window.portalToast({ type: 'info', title: msg || 'Info' });
    }
  };

  var spinnerHtml = '<span class="btn__spinner" aria-hidden="true"></span>';

  /**
   * Pone o quita estado loading en un botón (spinner, disabled).
   * @param {HTMLButtonElement|HTMLElement} btn
   * @param {boolean} loading
   * @param {string} [loadingText] - texto mientras carga (ej. 'Guardando…')
   */
  window.uiSetButtonLoading = function (btn, loading, loadingText) {
    if (!btn) return;
    if (loading) {
      btn.setAttribute('data-ui-original-content', btn.innerHTML);
      btn.classList.add('btn--loading');
      btn.disabled = true;
      btn.innerHTML = (loadingText || 'Cargando…') + ' ' + spinnerHtml;
    } else {
      btn.classList.remove('btn--loading');
      btn.disabled = false;
      var orig = btn.getAttribute('data-ui-original-content');
      if (orig != null) {
        btn.removeAttribute('data-ui-original-content');
        btn.innerHTML = orig;
      }
    }
  };

  /**
   * Cierra overlays/drawers/modales y limpia estados loading para evitar UI rota.
   * Usar antes de mostrar modal "Sesión expirada" (401).
   */
  window.uiCloseAllOverlays = function () {
    try { document.body.classList.remove('no-scroll'); } catch (_) {}
    try { document.body.classList.remove('sidebar-open'); } catch (_) {}
    try { document.documentElement.classList.remove('sidebar-open'); } catch (_) {}

    // Overlays/drawers
    document.querySelectorAll('.ui-overlay.is-open, .cfdi-drawer-overlay.is-open, .provider-drawer-overlay.is-open').forEach(function (el) {
      try {
        el.classList.remove('is-open');
        el.hidden = true;
        el.setAttribute('aria-hidden', 'true');
      } catch (_) {}
    });

    // Modales genéricos
    document.querySelectorAll('.modal:not([hidden])').forEach(function (m) {
      try {
        m.hidden = true;
        m.setAttribute('aria-hidden', 'true');
        m.classList.remove('is-open');
      } catch (_) {}
    });

    // Drawer de facturas por proveedor (si existe)
    var providerPanel = document.getElementById('providerInvoicesPanel');
    if (providerPanel) {
      try {
        providerPanel.hidden = true;
        providerPanel.setAttribute('aria-hidden', 'true');
        providerPanel.classList.remove('is-open');
      } catch (_) {}
    }

    // PDF modal
    var pdfModal = document.getElementById('pdfModal');
    if (pdfModal && pdfModal.classList.contains('pdf-modal--open')) {
      try {
        pdfModal.classList.remove('pdf-modal--open');
        pdfModal.setAttribute('aria-hidden', 'true');
      } catch (_) {}
    }

    // User menu
    var userMenu = document.getElementById('userMenu');
    var userMenuBtn = document.getElementById('userMenuBtn');
    if (userMenu) { try { userMenu.hidden = true; userMenu.setAttribute('aria-hidden', 'true'); } catch (_) {} }
    if (userMenuBtn) { try { userMenuBtn.setAttribute('aria-expanded', 'false'); } catch (_) {} }

    // Sidebar backdrop
    var sidebarBackdrop = document.getElementById('sidebarBackdrop');
    if (sidebarBackdrop) { try { sidebarBackdrop.hidden = true; sidebarBackdrop.setAttribute('aria-hidden', 'true'); } catch (_) {} }

    // Limpiar botones en loading (evitar spinners colgados)
    document.querySelectorAll('.btn--loading,[data-ui-original-content]').forEach(function (btn) {
      if (typeof window.uiSetButtonLoading === 'function') {
        try { window.uiSetButtonLoading(btn, false); } catch (_) {}
      } else {
        try { btn.classList.remove('btn--loading'); btn.disabled = false; } catch (_) {}
      }
    });
  };

  /** P35: URLs que usan cache (Map TTL 10 min) para evitar duplicados */
  function isCachedApiUrl(url) {
    if (!url || typeof url !== 'string') return false;
    var path = url.split('?')[0];
    return path.indexOf('/api/catalogs/') !== -1 || path === '/api/customers' || path === '/api/products';
  }

  /**
   * Helper único: fetch con timeout y manejo base de 401.
   * - Timeout por defecto: 30s (abort)
   * - En 401: dispara modal "Sesión expirada" y limpia UI (si existe showSessionExpiredModal)
   * @param {string} url
   * @param {RequestInit} [opts]
   * @param {number} [timeoutMs]
   * @returns {Promise<Response>}
   */
  window.portalFetchWithTimeout = function (url, opts, timeoutMs) {
    var options = Object.assign({ credentials: 'same-origin' }, opts || {});
    var ms = Number.isFinite(timeoutMs) ? timeoutMs : 30000;

    var controller = new AbortController();
    var timedOut = false;
    var t = setTimeout(function () {
      timedOut = true;
      try { controller.abort(); } catch (_) {}
    }, ms);

    // Si ya venía un signal (p. ej. navegación), encadenarlo al nuestro
    var externalSignal = options.signal;
    if (externalSignal && typeof externalSignal.addEventListener === 'function') {
      if (externalSignal.aborted) {
        try { controller.abort(); } catch (_) {}
      } else {
        externalSignal.addEventListener('abort', function () {
          try { controller.abort(); } catch (_) {}
        }, { once: true });
      }
    }

    options.signal = controller.signal;

    return fetch(url, options)
      .catch(function (err) {
        if (err && err.name === 'AbortError' && timedOut) {
          var te = new Error('Timeout');
          te.name = 'TimeoutError';
          te.isTimeout = true;
          throw te;
        }
        throw err;
      })
      .finally(function () {
        clearTimeout(t);
      });
  };

  /**
   * Helper JSON unificado para el portal (timeout + 401 + retry).
   * @param {string} url
   * @param {RequestInit} [opts]
   * @param {{ timeoutMs?: number, retry?: number }} [cfg]
   * @returns {Promise<{ ok: boolean, status: number, data?: any, error?: 'timeout'|'network'|'unauthorized'|'http'|'parse', detail?: string }>}
   */
  window.portalFetchJSON = async function (url, opts, cfg) {
    var options = Object.assign({ credentials: 'same-origin' }, opts || {});
    var timeoutMs = (cfg && Number.isFinite(cfg.timeoutMs)) ? cfg.timeoutMs : 30000;
    var retry = (cfg && Number.isFinite(cfg.retry)) ? cfg.retry : 1;

    var method = ((options.method || 'GET') + '').toUpperCase();
    var canRetry = (method === 'GET' || method === 'HEAD');

    // Headers defaults
    var headers = Object.assign({}, options.headers || {});
    if (!headers.Accept && !headers.accept) headers.Accept = 'application/json';
    options.headers = headers;

    // Cache layer para catálogos (solo GET)
    if (method === 'GET' && isCachedApiUrl(url) && typeof window.portalCatalogGetJson === 'function') {
      try {
        var cachedData = await window.portalCatalogGetJson(url, options);
        return { ok: true, status: 200, data: cachedData };
      } catch (err) {
        if (err && err.isTimeout) return { ok: false, status: 0, error: 'timeout', detail: 'La solicitud tardó demasiado. Revisa tu conexión e intenta de nuevo.' };
        return { ok: false, status: 0, error: 'network', detail: 'No pudimos conectar. Revisa tu conexión e intenta de nuevo.' };
      }
    }

    var attempts = Math.max(0, retry) + 1;
    for (var i = 0; i < attempts; i++) {
      try {
        var res = await window.portalFetchWithTimeout(url, options, timeoutMs);

        if (res && res.status === 401) {
          if (typeof window.uiCloseAllOverlays === 'function') window.uiCloseAllOverlays();
          if (typeof window.showSessionExpiredModal === 'function') window.showSessionExpiredModal();
          return { ok: false, status: 401, error: 'unauthorized', detail: 'Sesión expirada. Inicia sesión para continuar.' };
        }

        var status = res ? res.status : 0;
        var text = '';
        try { text = await res.text(); } catch (_) { text = ''; }

        var parsed = null;
        if (text) {
          try { parsed = JSON.parse(text); } catch (_) { parsed = null; }
        }

        if (!res.ok) {
          var detail = (parsed && (parsed.detail || parsed.message)) || res.statusText || ('Error ' + status);
          if (typeof detail !== 'string') detail = Array.isArray(detail) ? detail.join('; ') : ('Error ' + status);
          return { ok: false, status: status, error: 'http', detail: detail };
        }

        // OK: si no es JSON válido, devolver parse error (pero sin stack)
        if (text && parsed === null) {
          return { ok: false, status: status, error: 'parse', detail: 'Respuesta inválida del servidor. Intenta de nuevo.' };
        }
        return { ok: true, status: status, data: (text ? parsed : null) };
      } catch (err2) {
        var isTimeout = !!(err2 && err2.isTimeout);
        var isAbort = !!(err2 && err2.name === 'AbortError');
        if (isAbort && !isTimeout) {
          // abort externo (navegación/cancel)
          return { ok: false, status: 0, error: 'network', detail: 'Solicitud cancelada.' };
        }
        if (isTimeout) {
          if (canRetry && i < attempts - 1) {
            await new Promise(function (r) { setTimeout(r, 250); });
            continue;
          }
          return { ok: false, status: 0, error: 'timeout', detail: 'La solicitud tardó demasiado. Revisa tu conexión e intenta de nuevo.' };
        }
        // network / fetch failed
        if (canRetry && i < attempts - 1) {
          await new Promise(function (r) { setTimeout(r, 250); });
          continue;
        }
        return { ok: false, status: 0, error: 'network', detail: 'No pudimos conectar. Revisa tu conexión e intenta de nuevo.' };
      }
    }

    return { ok: false, status: 0, error: 'network', detail: 'No pudimos conectar. Intenta de nuevo.' };
  };

  /**
   * P24: Fetch JSON normalizado. Regla para cargas de listado: no usar toast.
   *   - response ok y data/lista vacía => renderEmptyState() ("Aún no hay …" + CTA)
   *   - status 401 => bloque "Sesión expirada" + enlace a /login
   *   - status >= 400 => renderErrorBlock("No se pudo cargar", "Reintentar")
   * P35: GET a /api/catalogs/*, /api/customers, /api/products usan cache en memoria (sin requests duplicados).
   * @param {string} url
   * @param {RequestInit} [opts] - credentials, signal, etc.
   * @returns {Promise<{ ok: boolean, status: number, data: any, error: string }>}
   */
  window.uiFetchJSON = function (url, opts) {
    var options = Object.assign({}, opts || {});
    return window.portalFetchJSON(url, options, { timeoutMs: 30000, retry: 1 })
      .then(function (r) {
        return { ok: !!r.ok, status: r.status || 0, data: r.data || null, error: r.detail || '' };
      });
  };

  /**
   * P24: Mensaje para bloque de error en carga de listado (no usar toast en cargas).
   * @param {{ status: number, data: any, error: string }} r - resultado de uiFetchJSON
   * @param {string} context - 'clientes' | 'proveedores' | 'productos' | 'cotizaciones' | 'emitidas' | 'recibidas'
   * @returns {string}
   */
  window.uiListLoadErrorText = function (r, context) {
    if (window.portalListLoadErrorMessage && r) {
      return window.portalListLoadErrorMessage({ status: r.status }, r.data, context);
    }
    return (r && r.error) ? r.error : 'Revisa tu conexión e intenta de nuevo.';
  };

  /**
   * P24: Extrae lista de la respuesta (array directo, data.data, data.customers, etc).
   * @param {*} data - respuesta de API
   * @returns {Array}
   */
  window.uiGetListFromResponse = function (data) {
    if (Array.isArray(data)) return data;
    if (data && Array.isArray(data.data)) return data.data;
    if (data && Array.isArray(data.customers)) return data.customers;
    if (data && Array.isArray(data.providers)) return data.providers;
    if (data && Array.isArray(data.products)) return data.products;
    if (data && Array.isArray(data.quotations)) return data.quotations;
    return [];
  };

  /**
   * P24: Mensaje para 401 (sesión expirada) con enlace a login. Usar en bloque de error, no toast.
   * @returns {string} HTML seguro para innerHTML
   */
  window.uiSessionExpiredMessage = function () {
    return 'Sesión expirada. <a href="/login">Inicia sesión</a>';
  };

  /**
   * P27: Espera hasta que hayan pasado al menos minMs desde shownAt (skeleton mínimo visible).
   * Uso: mostrar skeleton, fetch, await uiMinSkeletonDelay(skeletonShownAt, 300), luego render real/empty/error.
   * @param {number} shownAt - Date.now() cuando se mostró el skeleton
   * @param {number} [minMs] - mínimo ms (default 300)
   * @returns {Promise<void>}
   */
  window.uiMinSkeletonDelay = function (shownAt, minMs) {
    var min = (minMs == null || minMs < 0) ? 300 : minMs;
    var elapsed = Date.now() - (shownAt || 0);
    var wait = Math.max(0, min - elapsed);
    if (wait <= 0) return Promise.resolve();
    return new Promise(function (resolve) { setTimeout(resolve, wait); });
  };

  /**
   * P27: Genera HTML de filas skeleton para tablas (Emitidas, Recibidas, Clientes, etc.).
   * @param {number} cols - número de celdas por fila (colspan)
   * @param {number} rows - número de filas
   * @returns {string}
   */
  window.uiSkeletonTableRows = function (cols, rows) {
    var r = '';
    for (var i = 0; i < rows; i++) {
      r += '<tr><td colspan="' + cols + '"><div class="skeleton skeleton--row-46"></div></td></tr>';
    }
    return r;
  };

  /**
   * P27: Genera HTML de N cards skeleton (lista móvil Emitidas/Recibidas).
   * @param {number} count - número de cards
   * @param {{ cardClass?: string, height?: number }} [opts] - cardClass default 'invoice-card-mobile', height default 72
   * @returns {string}
   */
  window.uiSkeletonCards = function (count, opts) {
    var o = opts || {};
    var cardClass = o.cardClass || 'invoice-card-mobile';
    var h = (o.height != null && o.height > 0) ? o.height : 72;
    var html = '';
    for (var i = 0; i < count; i++) {
      // default: 72px => usa clase; para alturas distintas cae en inline (caso raro)
      if (h === 72) html += '<div class="' + cardClass + '"><div class="skeleton skeleton--card-72"></div></div>';
      else html += '<div class="' + cardClass + '"><div class="skeleton" style="height:' + h + 'px;border-radius:12px;"></div></div>';
    }
    return html;
  };

  /**
   * P26 Success Overlay Premium: blur, check animado, auto-dismiss opcional.
   * P26: Overlay tipo Phantom/Revolut al completar (guardar cliente/producto/proveedor, validar FIEL, sync, timbrar).
   * Blur, check animado, auto-dismiss opcional. Cerrar no rompe flujo.
   * @param {object} opts
   * @param {string} [opts.title] - ej. 'Factura emitida'
   * @param {string} [opts.message] - ej. 'Tu factura se generó correctamente.'
   * @param {Array<{label, href?}>|Array<{label, onClick?}>} [opts.actions] - botones (href = enlace, onClick = función). Si vacío, se añade "Entendido".
   * @param {string} [opts.copyLink] - texto a copiar al portapapeles
   * @param {string} [opts.copyLabel] - texto del botón copiar (default 'Copiar link')
   * @param {number} [opts.autoDismiss] - ms para cerrar automáticamente (opcional)
   */
  window.uiSuccessOverlay = function (opts) {
    var container = document.getElementById('successOverlay');
    if (!container) {
      container = document.createElement('div');
      container.id = 'successOverlay';
      container.className = 'success-overlay';
      container.setAttribute('role', 'dialog');
      container.setAttribute('aria-modal', 'true');
      container.setAttribute('aria-labelledby', 'successOverlayTitle');
      container.hidden = true;
      document.body.appendChild(container);
    }

    var title = (opts && opts.title) || 'Listo';
    var message = (opts && opts.message) || '';
    var actions = (opts && opts.actions && opts.actions.length) ? opts.actions : [{ label: 'Entendido', onClick: function () { if (window.uiSuccessOverlayClose) window.uiSuccessOverlayClose(); } }];
    var copyLink = opts && opts.copyLink;
    var copyLabel = (opts && opts.copyLabel) || 'Copiar link';
    var autoDismiss = opts && Number.isFinite(opts.autoDismiss) ? opts.autoDismiss : 0;

    var checkmarkSvg = '<svg viewBox="0 0 72 72" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true"><path class="success-overlay__check" d="M14 38l14 14 30-30" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/></svg>';

    var actionsHtml = '';
    if (copyLink) {
      actionsHtml += '<button type="button" class="btn btn--secondary success-overlay__copy-btn" data-copy-text="' + escapeHtml(copyLink) + '">' + escapeHtml(copyLabel) + '</button>';
    }
    actions.forEach(function (a) {
      if (a.href) {
        actionsHtml += '<a href="' + escapeHtml(a.href) + '" class="btn btn--primary">' + escapeHtml(a.label) + '</a>';
      } else if (a.onClick && typeof a.onClick === 'function') {
        actionsHtml += '<button type="button" class="btn btn--primary" data-action-callback>' + escapeHtml(a.label) + '</button>';
      }
    });

    container.innerHTML = '<div class="success-overlay__backdrop" data-close-overlay></div><div class="success-overlay__card">' +
      '<div class="success-overlay__icon">' + checkmarkSvg + '</div>' +
      '<h2 id="successOverlayTitle" class="success-overlay__title">' + escapeHtml(title) + '</h2>' +
      (message ? '<p class="success-overlay__message">' + escapeHtml(message) + '</p>' : '') +
      '<div class="success-overlay__actions">' + actionsHtml + '</div></div>';

    var close = function () {
      container.hidden = true;
      container.removeAttribute('aria-labelledby');
      container._close = null;
      if (container._autoDismissTimer) {
        clearTimeout(container._autoDismissTimer);
        container._autoDismissTimer = null;
      }
      document.removeEventListener('keydown', closeOnEscape);
      document.body.classList.remove('no-scroll');
    };
    container._close = close;
    var closeOnEscape = function (e) {
      if (e.key === 'Escape') { close(); e.preventDefault(); }
    };

    container.querySelectorAll('[data-close-overlay]').forEach(function (el) {
      el.addEventListener('click', close);
    });
    document.addEventListener('keydown', closeOnEscape);
    document.body.classList.add('no-scroll');

    container.querySelectorAll('.success-overlay__copy-btn').forEach(function (btn) {
      var text = btn.getAttribute('data-copy-text');
      btn.addEventListener('click', function () {
        if (!navigator.clipboard || !text) return;
        navigator.clipboard.writeText(text).then(function () {
          if (window.uiToast) window.uiToast({ type: 'success', title: 'Copiado', message: 'Link copiado al portapapeles.', timeout: 2000 });
        }).catch(function () {
          if (window.uiToast) window.uiToast({ type: 'info', title: 'Copia manual', message: 'Selecciona y copia el link desde la barra de direcciones.', timeout: 4000 });
        });
      });
    });

    var callbacks = actions.filter(function (a) { return a && typeof a.onClick === 'function'; });
    container.querySelectorAll('[data-action-callback]').forEach(function (btn, i) {
      var a = callbacks[i];
      if (a) {
        btn.addEventListener('click', function () {
          a.onClick();
          close();
        });
      }
    });

    container.hidden = false;
    if (autoDismiss > 0) {
      container._autoDismissTimer = setTimeout(close, autoDismiss);
    }
  };

  /**
   * Cierra el success overlay y limpia timer/eventos (P26: no rompe flujo).
   */
  window.uiSuccessOverlayClose = function () {
    var el = document.getElementById('successOverlay');
    if (el && typeof el._close === 'function') {
      el._close();
    } else if (el) {
      el.hidden = true;
      document.body.classList.remove('no-scroll');
    }
  };

  /**
   * Muestra checkmark de éxito en un botón (guardar/enviar/generar) y restaura después.
   * @param {HTMLButtonElement} btn - botón que disparó la acción
   * @param {number} [durationMs] - ms que se muestra el check (default 1600)
   */
  window.uiSetButtonSuccess = function (btn, durationMs) {
    if (!btn) return;
    var duration = Number(durationMs) || 1600;
    var originalHtml = btn.innerHTML;
    var checkSvg = '<span class="btn-success-check" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6L9 17l-5-5"/></svg></span>';
    btn.disabled = true;
    btn.classList.add('btn--success');
    btn.innerHTML = checkSvg;
    setTimeout(function () {
      btn.classList.remove('btn--success');
      btn.disabled = false;
      btn.innerHTML = originalHtml;
    }, duration);
  };

  /* ----- Page loading bar (fetches / listas); reducido en CSS ----- */
  (function () {
    var bar = document.getElementById('pageLoadingBar');
    if (!bar) return;
    var active = false;
    function start() {
      if (active) return;
      active = true;
      bar.classList.remove('page-loading-bar--done');
      bar.classList.add('page-loading-bar--active');
      bar.setAttribute('aria-hidden', 'false');
      bar.style.transform = 'scaleX(0)';
      requestAnimationFrame(function () {
        bar.style.transform = '';
      });
    }
    function done() {
      bar.classList.remove('page-loading-bar--active');
      bar.classList.add('page-loading-bar--done');
      bar.setAttribute('aria-hidden', 'true');
      setTimeout(function () {
        bar.classList.remove('page-loading-bar--done');
        bar.style.transform = 'scaleX(0)';
        active = false;
      }, 150);
    }
    window.portalProgressBar = { start: start, done: done };
    document.addEventListener('click', function (e) {
      var a = e.target.closest('a[href^="/"]');
      if (!a) return;
      var href = (a.getAttribute('href') || '').trim();
      if (!href || href === '#' || href.indexOf('#') === 0) return;
      if (href === '/portal' || href.indexOf('/portal/') === 0) return; /* P23 handles portal */
      if (a.target === '_blank' || a.hasAttribute('download')) return;
      e.preventDefault();
      start();
      window.location.href = href;
    }, true);
    window.addEventListener('pageshow', function (e) {
      if (e.persisted) done();
    });
    window.addEventListener('load', function () {
      if (active) done();
    });
  })();

  /* ----- P23: Transiciones de ruta + topProgress (solo /portal/, respeta reduced-motion) ----- */
  (function () {
    var topBar = document.getElementById('topProgress');
    var pageContent = document.getElementById('pageContent');
    var reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    function progressStart() {
      if (!topBar) return;
      topBar.classList.remove('top-progress--done');
      topBar.classList.add('top-progress--active');
      topBar.setAttribute('aria-hidden', 'false');
      topBar.style.transform = 'scaleX(0)';
      requestAnimationFrame(function () {
        topBar.style.transform = '';
      });
    }
    function progressDone() {
      if (!topBar) return;
      topBar.classList.remove('top-progress--active');
      topBar.classList.add('top-progress--done');
      var delay = reduceMotion ? 0 : 120;
      setTimeout(function () {
        topBar.setAttribute('aria-hidden', 'true');
        topBar.classList.remove('top-progress--done');
        topBar.style.transform = 'scaleX(0)';
      }, delay);
    }

    document.addEventListener('click', function (e) {
      var a = e.target.closest('a[href]');
      if (!a) return;
      var href = (a.getAttribute('href') || '').trim();
      if (href !== '/portal' && href.indexOf('/portal/') !== 0) return;
      if (a.target === '_blank' || a.hasAttribute('download')) return;
      if (e.ctrlKey || e.metaKey || e.button !== 0) return;
      if (href.indexOf('/download/') !== -1 || href.indexOf('/api/') === 0) return;
      e.preventDefault();
      if (!reduceMotion && pageContent) pageContent.classList.add('page-leave');
      progressStart();
      var targetUrl = a.href || href;
      setTimeout(function () {
        window.location.href = targetUrl;
      }, reduceMotion ? 0 : 120);
    }, true);

    function onPageReady() {
      if (!reduceMotion && pageContent) {
        requestAnimationFrame(function () {
          pageContent.style.opacity = '1';
        });
        setTimeout(function () {
          pageContent.classList.remove('page-enter');
          pageContent.style.opacity = '';
        }, 180);
      }
      progressDone();
    }
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', onPageReady);
    } else {
      onPageReady();
    }
  })();
})();
