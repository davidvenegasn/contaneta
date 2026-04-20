/**
 * Command Palette (Cmd+K / Ctrl+K) — Global search.
 * Searches nav items locally + clients/providers/products/invoices/movements via API.
 * No dependencies — vanilla JS.
 */
(function () {
  'use strict';

  var icons = {
    search: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/></svg>',
    home: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><path d="M3 10.5 12 3l9 7.5"/><path d="M5.5 10.5V21h13V10.5"/><path d="M10 21v-6h4v6"/></svg>',
    doc: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H7a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V7z"/><path d="M14 2v5h5"/></svg>',
    users: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75"><circle cx="9" cy="8" r="4"/><path d="M3 20c0-3 3-5 6-5s6 2 6 5"/></svg>',
    box: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><path d="M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4"/></svg>',
    chart: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round"><path d="M13 17V9"/><path d="M18 17V5"/><path d="M3 3v16a2 2 0 0 0 2 2h16"/><path d="M8 17v-3"/></svg>',
    bank: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round"><path d="M3 10h18"/><path d="M5 10V20m4-10V20m6-10V20m4-10V20"/><path d="M2.5 10 12 4l9.5 6"/><path d="M4 20h16"/></svg>',
    plus: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round"><path d="M12 5v14M5 12h14"/></svg>',
    settings: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>',
    quote: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round"><path d="M6 2a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6H6z"/><path d="M14 2v6h6"/></svg>',
    arrow: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14"/><path d="m12 5 7 7-7 7"/></svg>',
    provider: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>',
    money: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round"><path d="M12 2v20M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/></svg>'
  };

  var navItems = [
    { label: 'Inicio', sub: 'Dashboard principal', href: '/portal/home', icon: 'home', keywords: 'inicio home dashboard panel' },
    { label: 'Nueva factura', sub: 'Crear factura de ingreso', href: '/portal/create', icon: 'plus', keywords: 'nueva factura crear emitir timbrar invoice create' },
    { label: 'Facturas', sub: 'Emitidas y recibidas', href: '/portal/facturas', icon: 'doc', keywords: 'facturas emitidas recibidas issued received' },
    { label: 'Catálogos', sub: 'Clientes, productos, proveedores', href: '/portal/catalogos', icon: 'users', keywords: 'catalogos clientes productos proveedores' },
    { label: 'Cotizaciones', sub: 'Cotizaciones enviadas', href: '/portal/cotizaciones', icon: 'quote', keywords: 'cotizaciones quotes' },
    { label: 'Movimientos', sub: 'Estado de cuenta y conciliación', href: '/portal/movimientos', icon: 'bank', keywords: 'movimientos bancarios bank conciliacion' },
    { label: 'Convertir edo. cuenta', sub: 'PDF bancario a Excel', href: '/portal/convertir-edo-cuenta', icon: 'bank', keywords: 'convertir estado cuenta pdf excel bank importar' },
    { label: 'Conectar SAT (FIEL)', sub: 'Configurar credenciales SAT', href: '/portal/config/sat', icon: 'settings', keywords: 'sat fiel configurar credenciales sync sincronizar' },
    { label: 'Datos fiscales', sub: 'RFC, razón social, régimen', href: '/portal/datos-fiscales', icon: 'settings', keywords: 'datos fiscales rfc razon social regimen' },
    { label: 'Mi plan', sub: 'Membresía y facturación', href: '/portal/plan', icon: 'settings', keywords: 'plan membresia facturacion billing' },
    { label: 'Guías', sub: 'Tutoriales y ayuda', href: '/portal/guides', icon: 'doc', keywords: 'guias tutoriales ayuda help' }
  ];

  var backdrop, palette, input, resultsList, activeIndex = -1, allItems = [], isOpen = false;
  var searchTimer = null;
  var lastQuery = '';
  var apiResults = null;
  var isSearching = false;

  function escapeHtml(s) {
    if (!s) return '';
    var d = document.createElement('div');
    d.textContent = s;
    return d.innerHTML;
  }

  function highlightMatch(text, query) {
    if (!query) return escapeHtml(text);
    var lower = (text || '').toLowerCase();
    var qLower = query.toLowerCase();
    var i = lower.indexOf(qLower);
    if (i === -1) return escapeHtml(text);
    return escapeHtml(text.slice(0, i)) + '<span class="cmd-palette__match">' + escapeHtml(text.slice(i, i + query.length)) + '</span>' + escapeHtml(text.slice(i + query.length));
  }

  function fmtMoney(n) {
    if (!n && n !== 0) return '';
    return '$' + Number(n).toLocaleString('es-MX', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }

  function buildDOM() {
    backdrop = document.createElement('div');
    backdrop.className = 'cmd-palette-backdrop';
    backdrop.addEventListener('click', close);

    palette = document.createElement('div');
    palette.className = 'cmd-palette';
    palette.setAttribute('role', 'dialog');
    palette.setAttribute('aria-modal', 'true');
    palette.setAttribute('aria-label', 'Búsqueda global');

    palette.innerHTML =
      '<div class="cmd-palette__search">' +
        '<span class="cmd-palette__search-icon">' + icons.search + '</span>' +
        '<input class="cmd-palette__input" type="text" placeholder="Buscar facturas, clientes, proveedores…" autocomplete="off" spellcheck="false" />' +
        '<kbd class="cmd-palette__kbd">esc</kbd>' +
      '</div>' +
      '<div class="cmd-palette__results" role="listbox"></div>' +
      '<div class="cmd-palette__footer">' +
        '<span><kbd>↑</kbd> <kbd>↓</kbd> navegar</span>' +
        '<span><kbd>↵</kbd> abrir</span>' +
        '<span><kbd>?</kbd> atajos</span>' +
      '</div>';

    document.body.appendChild(backdrop);
    document.body.appendChild(palette);

    input = palette.querySelector('.cmd-palette__input');
    resultsList = palette.querySelector('.cmd-palette__results');

    input.addEventListener('input', onInput);
    palette.addEventListener('keydown', onKeydown);
  }

  function open() {
    if (isOpen) return;
    if (!palette) buildDOM();
    isOpen = true;
    backdrop.classList.add('is-open');
    palette.classList.add('is-open');
    document.body.classList.add('no-scroll');
    input.value = '';
    activeIndex = -1;
    apiResults = null;
    isSearching = false;
    renderResults('');
    requestAnimationFrame(function () { input.focus(); });
  }

  function close() {
    if (!isOpen) return;
    isOpen = false;
    backdrop.classList.remove('is-open');
    palette.classList.remove('is-open');
    document.body.classList.remove('no-scroll');
  }

  function navigate(href) {
    close();
    if (href) window.location.href = href;
  }

  function onInput() {
    var q = (input.value || '').trim();
    activeIndex = -1;

    // Local nav results render immediately
    renderResults(q);

    // Debounced API search
    clearTimeout(searchTimer);
    if (q.length >= 2) {
      lastQuery = q;
      isSearching = true;
      searchTimer = setTimeout(function () { searchAPI(q); }, 300);
    } else {
      apiResults = null;
      isSearching = false;
    }
  }

  function matchItem(item, q) {
    if (!q) return true;
    var lower = q.toLowerCase();
    var haystack = (item.label + ' ' + (item.sub || '') + ' ' + (item.keywords || '')).toLowerCase();
    return haystack.indexOf(lower) !== -1;
  }

  function renderResults(q) {
    var html = '';
    allItems = [];

    // Navigation (local, instant)
    var navMatches = navItems.filter(function (item) { return matchItem(item, q); });
    if (navMatches.length > 0) {
      html += '<div class="cmd-palette__group-title">Páginas</div>';
      navMatches.forEach(function (item) {
        var idx = allItems.length;
        allItems.push(item);
        html += renderItem(item, idx, q);
      });
    }

    // API results
    if (q.length >= 2 && apiResults) {
      var sections = [
        { key: 'clientes', title: 'Clientes', icon: 'users' },
        { key: 'proveedores', title: 'Proveedores', icon: 'provider' },
        { key: 'productos', title: 'Productos', icon: 'box' },
        { key: 'facturas', title: 'Facturas', icon: 'doc' },
        { key: 'movimientos', title: 'Movimientos', icon: 'bank' }
      ];
      sections.forEach(function (sec) {
        var items = apiResults[sec.key] || [];
        if (items.length === 0) return;
        html += '<div class="cmd-palette__group-title">' + sec.title + '</div>';
        items.forEach(function (r) {
          var item;
          if (sec.key === 'clientes') {
            item = { label: r.nombre, sub: r.rfc, href: r.url, icon: sec.icon };
          } else if (sec.key === 'proveedores') {
            item = { label: r.nombre, sub: r.rfc + (r.facturas ? ' · ' + r.facturas + ' facturas' : ''), href: r.url, icon: sec.icon };
          } else if (sec.key === 'productos') {
            item = { label: r.nombre, sub: r.clave + (r.precio ? ' · ' + fmtMoney(r.precio) : ''), href: r.url, icon: sec.icon };
          } else if (sec.key === 'facturas') {
            item = { label: r.nombre, sub: r.tipo + ' · ' + r.fecha + ' · ' + fmtMoney(r.total), href: r.url, icon: sec.icon };
          } else if (sec.key === 'movimientos') {
            item = { label: r.concepto, sub: r.fecha + ' · ' + fmtMoney(r.monto), href: r.url, icon: sec.icon };
          }
          if (item) {
            var idx = allItems.length;
            allItems.push(item);
            html += renderItem(item, idx, q);
          }
        });
      });
    }

    // Loading state
    if (q.length >= 2 && isSearching && !apiResults) {
      html += '<div class="cmd-palette__loading">';
      html += '<span class="spinner spinner--sm" aria-hidden="true"></span>';
      html += '<span>Buscando…</span>';
      html += '</div>';
    }

    if (q.length >= 2 && apiResults && apiResults._error) {
      html += '<div class="cmd-palette__empty">No se pudo buscar. Verifica tu conexión.</div>';
    } else if (allItems.length === 0 && q && !isSearching) {
      html = '<div class="cmd-palette__empty">No se encontraron resultados para "' + escapeHtml(q) + '"</div>';
    }

    resultsList.innerHTML = html;

    // Click handlers
    resultsList.querySelectorAll('.cmd-palette__item').forEach(function (el) {
      el.addEventListener('click', function (e) {
        e.preventDefault();
        var idx = parseInt(el.getAttribute('data-idx'), 10);
        if (allItems[idx]) navigate(allItems[idx].href);
      });
    });
  }

  function renderItem(item, idx, q) {
    var iconSvg = icons[item.icon] || icons.arrow;
    return '<div class="cmd-palette__item' + (idx === activeIndex ? ' is-active' : '') + '" data-idx="' + idx + '" role="option">' +
      '<div class="cmd-palette__item-icon">' + iconSvg + '</div>' +
      '<div class="cmd-palette__item-text">' +
        '<div class="cmd-palette__item-label">' + highlightMatch(item.label, q) + '</div>' +
        (item.sub ? '<div class="cmd-palette__item-sub">' + highlightMatch(item.sub, q) + '</div>' : '') +
      '</div>' +
    '</div>';
  }

  function searchAPI(q) {
    var fetchFn = window.portalFetchJSON || function(url) {
      return fetch(url, { credentials: 'same-origin' }).then(function(r) { return r.json(); });
    };
    fetchFn('/api/search?q=' + encodeURIComponent(q)).then(function (r) {
      if (lastQuery !== q) return; // stale
      apiResults = r.data || r;
      isSearching = false;
      renderResults(q);
    }).catch(function () {
      isSearching = false;
      apiResults = { _error: true, clientes: [], proveedores: [], productos: [], facturas: [], movimientos: [] };
      renderResults(q);
    });
  }

  function onKeydown(e) {
    if (e.key === 'Escape') {
      e.preventDefault();
      close();
      return;
    }
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      activeIndex = Math.min(activeIndex + 1, allItems.length - 1);
      updateActive();
      return;
    }
    if (e.key === 'ArrowUp') {
      e.preventDefault();
      activeIndex = Math.max(activeIndex - 1, 0);
      updateActive();
      return;
    }
    if (e.key === 'Enter') {
      e.preventDefault();
      if (activeIndex >= 0 && allItems[activeIndex]) {
        navigate(allItems[activeIndex].href);
      }
      return;
    }
  }

  function updateActive() {
    var items = resultsList.querySelectorAll('.cmd-palette__item');
    items.forEach(function (el, i) {
      if (i === activeIndex) {
        el.classList.add('is-active');
        el.scrollIntoView({ block: 'nearest' });
      } else {
        el.classList.remove('is-active');
      }
    });
  }

  // Global keyboard shortcut: Cmd+K / Ctrl+K
  document.addEventListener('keydown', function (e) {
    if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
      e.preventDefault();
      if (isOpen) close();
      else open();
    }
  });

  // Expose globally for topbar button trigger
  window.openCommandPalette = open;
})();
