/**
 * QuickInvoice (reusable): bootstrap + pickers + modal "Factura rápida".
 *
 * API:
 *   window.QuickInvoice.open({ preselectedProductId?, preselectedCustomerId?, preselectedCustomerRfc?, presetLines? })
 *   window.QuickInvoice.setSelectedProduct(idOrObj)
 *   window.QuickInvoice.setSelectedCustomer(idOrObj)
 *
 * Compat:
 *   window.quickInvoiceReload() mantiene el contrato legacy del Home.
 *   window.__quickCustomersData / __quickProductsData se siguen exponiendo.
 */
(function () {
  'use strict';

  var BOOTSTRAP_URL = '/api/quick-invoice/bootstrap';

  // Home (opcional)
  var customerHidden = document.getElementById('quickCustomer');
  var productHidden = document.getElementById('quickProduct');
  var qselCustomer = document.getElementById('qselCustomer');
  var qselProduct = document.getElementById('qselProduct');
  var homeBtn = document.getElementById('quickInvoiceBtn');
  var homeHint = document.getElementById('quickInvoiceBtnHint');

  // Quick invoice modal (reusable)
  var modal = document.getElementById('quickInvoiceModal');
  var modalBackdrop = document.getElementById('quickInvoiceModalBackdrop');
  var modalClose = document.getElementById('quickInvoiceModalClose');
  var modalCancel = document.getElementById('quickInvoiceModalCancel');
  var modalSubmit = document.getElementById('quickInvoiceModalSubmit');
  var modalError = document.getElementById('quickInvoiceModalError');
  var modalPlanUsage = document.getElementById('quickInvoicePlanUsage');
  var modalCustomerName = document.getElementById('quickModalCustomerName');
  var modalCustomerZip = document.getElementById('quickModalCustomerZip');
  var modalCustomerTaxSystem = document.getElementById('quickModalCustomerTaxSystem');
  var modalCustomerEmail = document.getElementById('quickModalCustomerEmail');
  var modalAutoEmail = document.getElementById('quickModalAutoEmail');
  var modalProductDesc = document.getElementById('quickModalProductDesc');
  var modalProductKey = document.getElementById('quickModalProductKey');
  var modalProdservBtn = document.getElementById('quickModalProdservBtn');
  var modalUnitKey = document.getElementById('quickModalUnitKey');
  var unidadDatalist = document.getElementById('quickUnidadList');
  var modalQty = document.getElementById('quickModalQty');
  var modalUnitPrice = document.getElementById('quickModalUnitPrice');
  var modalIvaRate = document.getElementById('quickModalIvaRate');
  var modalIsrRetRate = document.getElementById('quickModalIsrRetRate');
  var modalIvaRetRate = document.getElementById('quickModalIvaRetRate');
  var modalCurrency = document.getElementById('quickModalCurrency');
  var modalExchangeRate = document.getElementById('quickModalExchangeRate');
  var modalExchangeRateWrap = document.getElementById('quickModalExchangeRateWrap');
  var modalCfdiUse = document.getElementById('quickModalCfdiUse');
  var modalPaymentForm = document.getElementById('quickModalPaymentForm');
  var modalPaymentMethod = document.getElementById('quickModalPaymentMethod');
  var modalItemsSummary = document.getElementById('quickModalItemsSummary');
  var modalSingleConcept = document.getElementById('quickModalSingleConcept');
  var modalProdservDesc = document.getElementById('quickModalProdservDesc');
  var modalUnitDesc = document.getElementById('quickModalUnitDesc');

  // Modales: crear cliente / producto (opcionales; usados en Home)
  var addCustomerBtn = document.getElementById('quickAddCustomerBtn');
  var addCustomerModal = document.getElementById('quickAddCustomerModal');
  var addCustomerBackdrop = document.getElementById('quickAddCustomerBackdrop');
  var addCustomerClose = document.getElementById('quickAddCustomerClose');
  var addCustomerCancel = document.getElementById('quickAddCustomerCancel');
  var addCustomerSave = document.getElementById('quickAddCustomerSave');
  var addCustomerError = document.getElementById('quickAddCustomerError');
  var addCustomerRfc = document.getElementById('quickCustomerRfc');
  var addCustomerName = document.getElementById('quickCustomerName');
  var addCustomerZip = document.getElementById('quickCustomerZip');
  var addCustomerTaxSystem = document.getElementById('quickCustomerTaxSystem');
  var addCustomerUsoCfdi = document.getElementById('quickCustomerUsoCfdi');
  var addCustomerEmail = document.getElementById('quickCustomerEmail');
  var addCustomerAlias = document.getElementById('quickCustomerAlias');

  var addProductBtn = document.getElementById('quickAddProductBtn');
  var addProductModal = document.getElementById('quickAddProductModal');
  var addProductBackdrop = document.getElementById('quickAddProductBackdrop');
  var addProductClose = document.getElementById('quickAddProductClose');
  var addProductCancel = document.getElementById('quickAddProductCancel');
  var addProductSave = document.getElementById('quickAddProductSave');
  var addProductError = document.getElementById('quickAddProductError');
  var addProductDesc = document.getElementById('quickProductDesc');
  var addProductKey = document.getElementById('quickProductKey');
  var addProductUnitKey = document.getElementById('quickProductUnitKey');
  var addProductUnitPrice = document.getElementById('quickProductUnitPrice');
  var addProductIvaRate = document.getElementById('quickProductIvaRate');
  var addProductProdservBtn = document.getElementById('quickProductProdservBtn');

  // Modal: buscar ProdServ
  var prodservModal = document.getElementById('quickProdservModal');
  var prodservModalInput = document.getElementById('quickProdservModalInput');
  var prodservModalResults = document.getElementById('quickProdservModalResults');
  var _prodservTargetInputId = null;
  var _prodservAbort = null;

  window.__quickCustomersData = window.__quickCustomersData || [];
  window.__quickProductsData = window.__quickProductsData || [];

  var state = {
    bootstrap: null,
    defaults: null,
    customers: window.__quickCustomersData,
    products: window.__quickProductsData,
    bootstrapPromise: null,
    catalogsPromise: null,
    currentCustomerId: null,
    currentProductId: null,
    presetLines: null,
    // para flows como "si falta cliente, abrir picker y luego abrir modal"
    _pendingOpenAfterPick: null,
    // Replacement mode: when set, the new invoice replaces the original
    replaces_uuid: null,
    prefillCfdiUse: null,
    prefillPaymentForm: null,
    prefillPaymentMethod: null,
    prefillCurrency: null,
  };

  function openPortal(modalEl, opts) {
    if (!modalEl) return;
    if (typeof window.openPortalModal === 'function') return window.openPortalModal(modalEl, opts || {});
    // fallback legacy
    try {
      modalEl.hidden = false;
      modalEl.classList.add('is-open');
      modalEl.setAttribute('aria-hidden', 'false');
      document.body.classList.add('no-scroll');
      if (typeof window.uiTrapFocus === 'function') window.uiTrapFocus(modalEl);
    } catch (_) {}
  }

  function closePortal(modalEl) {
    if (!modalEl) return;
    if (typeof window.closePortalModal === 'function') return window.closePortalModal(modalEl);
    // fallback legacy
    try {
      if (typeof window.uiReleaseFocusTrap === 'function') window.uiReleaseFocusTrap();
      modalEl.hidden = true;
      modalEl.classList.remove('is-open');
      modalEl.setAttribute('aria-hidden', 'true');
      document.body.classList.remove('no-scroll');
    } catch (_) {}
  }

  function toast(payload) {
    if (window.uiToast) return window.uiToast(payload);
    if (window.portalToast) return window.portalToast(payload);
  }

  function norm(s) {
    return String(s || '').toLowerCase().trim();
  }

  function parseNum(v) {
    if (v == null) return NaN;
    var s = String(v).replace(/[,$\s]/g, '');
    if (!s) return NaN;
    var n = Number(s);
    return Number.isFinite(n) ? n : NaN;
  }

  function fmtMoney(n) {
    try {
      return new Intl.NumberFormat('es-MX', { style: 'currency', currency: 'MXN' }).format(Number(n) || 0);
    } catch (e) {
      return '$' + (Number(n) || 0).toFixed(2);
    }
  }

  function formatMoneyInput(input) {
    if (!input) return;
    var n = parseNum(input.value);
    if (!Number.isFinite(n)) return;
    input.value = n.toFixed(2);
  }

  function getSelectedIvaRate() {
    var v = (modalIvaRate && modalIvaRate.value) ? String(modalIvaRate.value) : '0.16';
    if (v === 'EXENTO') return { rate: 0, label: 'Exento', exento: true };
    var rate = parseNum(v);
    if (!Number.isFinite(rate)) rate = 0.16;
    return { rate: rate, label: String(Math.round(rate * 100)) + '%', exento: false };
  }

  function debounce(fn, ms) {
    var t = null;
    return function () {
      var args = arguments;
      clearTimeout(t);
      t = setTimeout(function () { fn.apply(null, args); }, ms);
    };
  }

  function httpJson(url, fetchOpts, toolOpts) {
    var opts = fetchOpts || {};
    var t = toolOpts || {};
    if (typeof window.portalFetchJSON === 'function') {
      return window.portalFetchJSON(url, opts, t);
    }
    return fetch(url, opts).then(function (r) {
      return r.json().then(function (data) {
        return { ok: r.ok, status: r.status, data: data };
      });
    });
  }

  function showInlineError(container, message) {
    if (!container) return;
    var el = container.querySelector('.qsel-error');
    if (el) {
      el.textContent = message;
      el.hidden = false;
    }
  }

  function hideInlineError(container) {
    if (!container) return;
    var el = container.querySelector('.qsel-error');
    if (el) el.hidden = true;
  }

  function setHomeBtnState() {
    if (!homeBtn) return;
    var cId = customerHidden ? String(customerHidden.value || '') : '';
    var pId = productHidden ? String(productHidden.value || '') : '';
    var ok = !!(cId && pId);
    homeBtn.disabled = !ok;
    if (homeHint) homeHint.textContent = ok ? '' : 'Elige cliente y producto';
  }

  function ensureBootstrap(force) {
    if (!force && state.bootstrap) return Promise.resolve(state.bootstrap);
    if (!force && state.bootstrapPromise) return state.bootstrapPromise;

    var fetchOpts = { credentials: 'same-origin' };
    state.bootstrapPromise = httpJson(BOOTSTRAP_URL, fetchOpts, { timeoutMs: 15000, retry: 1 })
      .then(function (res) {
        var data = (res && res.ok && res.data) ? res.data : null;
        if (data && data.ok === true && data.data) data = data.data;
        if (!data) throw new Error('No se pudo cargar bootstrap');

        state.bootstrap = data;
        state.defaults = (data && data.defaults) ? data.defaults : null;
        window.__quickInvoiceBootstrap = data;
        window.__quickInvoiceDefaults = state.defaults;

        var clients = data.clients || [];
        var products = data.products || [];

        state.customers = clients.map(function (c) {
          return {
            id: c.id,
            rfc: c.rfc,
            legal_name: c.legal_name || c.name,
            zip: c.zip,
            tax_system: c.regimen || c.tax_system,
            email: c.email,
          };
        });
        state.products = products.map(function (p) {
          return {
            id: p.id,
            description: p.description || p.name,
            product_key: p.product_key || p.prodserv,
            unit_key: p.unit_key || 'E48',
            unit_price: p.unit_price != null ? p.unit_price : p.price,
            iva_rate: p.iva_default != null ? p.iva_default : (p.iva_rate != null ? p.iva_rate : 0.16),
          };
        });

        window.__quickCustomersData = state.customers;
        window.__quickProductsData = state.products;

        // Auto-selección post-creación (Home)
        try {
          if (customerHidden && window.__quickAfterCustomerRfc) {
            var rfcToSelect = String(window.__quickAfterCustomerRfc || '').toUpperCase();
            var matchC = state.customers.find(function (c) { return String(c.rfc || '').toUpperCase() === rfcToSelect; });
            if (matchC) setSelectedCustomer(matchC);
            window.__quickAfterCustomerRfc = null;
          }
          if (productHidden && window.__quickAfterProductId != null) {
            var idToSelect = String(window.__quickAfterProductId);
            var matchP = state.products.find(function (p) { return String(p.id) === idToSelect; });
            if (matchP) setSelectedProduct(matchP);
            window.__quickAfterProductId = null;
          }
        } catch (_) {}

        return data;
      })
      .finally(function () {
        state.bootstrapPromise = null;
      });

    return state.bootstrapPromise;
  }

  function fillSelect(selectEl, items, valueKey, labelKey, selected) {
    if (!selectEl) return;
    selectEl.innerHTML = '';
    (Array.isArray(items) ? items : []).forEach(function (it) {
      var opt = document.createElement('option');
      opt.value = String(it[valueKey] || it.key || it.value || '');
      opt.textContent = String(it[labelKey] || it.label || it.name || opt.value);
      selectEl.appendChild(opt);
    });
    if (selected != null) selectEl.value = String(selected);
  }

  function renderPlanUsageBadge() {
    if (!modalPlanUsage) return;
    var pu = state.bootstrap && state.bootstrap.plan_usage;
    if (!pu) { modalPlanUsage.hidden = true; return; }
    var current = Number(pu.current) || 0;
    var limit = Number(pu.limit) || 0;
    var allowed = pu.allowed !== false;
    var cls = allowed ? 'badge badge--info' : 'badge badge--danger';
    var text = limit > 0
      ? (current + ' / ' + limit + ' facturas este mes')
      : (current + ' facturas este mes');
    if (!allowed) text += ' — Límite alcanzado';
    modalPlanUsage.innerHTML = '<span class="' + cls + '">' + text + '</span>';
    modalPlanUsage.hidden = false;
    if (modalSubmit) {
      if (!allowed) {
        modalSubmit.disabled = true;
        modalSubmit.title = 'Has alcanzado el límite de tu plan';
      }
    }
  }

  function populateCatalogSelects(cats) {
    if (!cats) return;
    var regimen = cats.regimen_fiscal || [];
    var uso = cats.uso_cfdi || [];
    var forma = cats.forma_pago || [];
    var metodo = cats.metodo_pago || [];
    var monedas = cats.monedas || [];

    fillSelect(modalCustomerTaxSystem, regimen, 'key', 'label', '');
    fillSelect(addCustomerTaxSystem, regimen, 'key', 'label', '');
    fillSelect(modalCfdiUse, uso, 'key', 'label', '');
    fillSelect(addCustomerUsoCfdi, uso, 'key', 'label', '');
    fillSelect(modalPaymentForm, forma, 'key', 'label', '');
    fillSelect(modalCurrency, monedas, 'key', 'label', 'MXN');

    if (metodo.length) {
      fillSelect(modalPaymentMethod, metodo, 'key', 'label', 'PUE');
    } else if (modalPaymentMethod) {
      modalPaymentMethod.innerHTML = '';
      [
        { key: 'PUE', label: 'Pago en una sola exhibición (PUE)' },
        { key: 'PPD', label: 'Pago en parcialidades o diferido (PPD)' }
      ].forEach(function (it) {
        var opt = document.createElement('option');
        opt.value = it.key;
        opt.textContent = it.label;
        modalPaymentMethod.appendChild(opt);
      });
    }
  }

  function ensureCatalogs() {
    if (state.catalogsPromise) return state.catalogsPromise;

    // If bootstrap already loaded and has catalogs, use them directly
    if (state.bootstrap && state.bootstrap.catalogs) {
      populateCatalogSelects(state.bootstrap.catalogs);
      return Promise.resolve();
    }

    // Fallback: load catalogs from individual endpoints if bootstrap didn't include them
    state.catalogsPromise = Promise.all([
      httpJson('/api/catalogs/regimen_fiscal', { credentials: 'same-origin' }, { timeoutMs: 20000, retry: 1 }),
      httpJson('/api/catalogs/uso_cfdi', { credentials: 'same-origin' }, { timeoutMs: 20000, retry: 1 }),
      httpJson('/api/catalogs/forma_pago', { credentials: 'same-origin' }, { timeoutMs: 20000, retry: 1 }),
      httpJson('/api/catalogs/moneda', { credentials: 'same-origin' }, { timeoutMs: 20000, retry: 1 }),
    ])
      .then(function (all) {
        populateCatalogSelects({
          regimen_fiscal: all[0] && all[0].data,
          uso_cfdi: all[1] && all[1].data,
          forma_pago: all[2] && all[2].data,
          monedas: all[3] && all[3].data,
        });
      })
      .catch(function () {
        // Fail-soft: el usuario aún puede editar manualmente.
      })
      .finally(function () {
        state.catalogsPromise = null;
      });

    return state.catalogsPromise;
  }

  function findCustomerById(id) {
    var s = String(id || '');
    return state.customers.find(function (c) { return String(c.id) === s; }) || null;
  }

  function findCustomerByRfc(rfc) {
    var x = String(rfc || '').toUpperCase().trim();
    if (!x) return null;
    return state.customers.find(function (c) { return String(c.rfc || '').toUpperCase() === x; }) || null;
  }

  function findProductById(id) {
    var s = String(id || '');
    return state.products.find(function (p) { return String(p.id) === s; }) || null;
  }

  function setSelectedCustomer(cOrId) {
    var c = (cOrId && typeof cOrId === 'object') ? cOrId : findCustomerById(cOrId);
    if (!c || c.id == null) return;
    state.currentCustomerId = String(c.id);
    window.__quickCurrentCustomerId = state.currentCustomerId;

    if (customerHidden) {
      customerHidden.value = String(c.id);
      customerHidden.dispatchEvent(new Event('change', { bubbles: true }));
    }
    var inp = document.getElementById('qselCustomerInput');
    if (inp) inp.value = (c.legal_name || c.name || c.rfc || '—').trim();

    setHomeBtnState();
  }

  function setSelectedProduct(pOrId) {
    var p = (pOrId && typeof pOrId === 'object') ? pOrId : findProductById(pOrId);
    if (!p || p.id == null) return;
    state.currentProductId = String(p.id);
    window.__quickCurrentProductId = state.currentProductId;

    if (productHidden) {
      productHidden.value = String(p.id);
      productHidden.dispatchEvent(new Event('change', { bubbles: true }));
    }
    var inp = document.getElementById('qselProductInput');
    if (inp) inp.value = (p.description || p.name || p.product_key || '—').trim();

    setHomeBtnState();
  }

  function openPicker(kind, onPick) {
    var isCustomer = kind === 'customer';
    var pickerModal = document.getElementById(isCustomer ? 'qiClientPickerModal' : 'qiProductPickerModal');
    var panel = document.getElementById(isCustomer ? 'qiClientPickerPanel' : 'qiProductPickerPanel');
    var search = document.getElementById(isCustomer ? 'qiClientPickerSearch' : 'qiProductPickerSearch');
    var listEl = document.getElementById(isCustomer ? 'qiClientPickerList' : 'qiProductPickerList');
    var countEl = document.getElementById(isCustomer ? 'qiClientPickerCount' : 'qiProductPickerCount');
    var opener = document.getElementById(isCustomer ? 'qiOpenClientPicker' : 'qiOpenProductPicker');
    if (!pickerModal || !panel || !search || !listEl) return;

    function currentList() {
      return isCustomer ? (state.customers || []) : (state.products || []);
    }

    function escHtml(s) {
      return String(s || '').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    }

    function render(q) {
      var term = norm(q);
      var all = currentList();
      var items = term
        ? all.filter(function (it) {
            if (isCustomer) return norm(it.legal_name || it.name).indexOf(term) !== -1 || norm(it.rfc).indexOf(term) !== -1;
            return norm(it.description || it.name).indexOf(term) !== -1 || norm(it.product_key || it.prodserv).indexOf(term) !== -1;
          })
        : all;

      listEl.innerHTML = '';
      if (countEl) countEl.textContent = all.length ? (items.length + ' de ' + all.length) : '';

      if (!all || all.length === 0) {
        listEl.innerHTML = '<div class="muted" style="padding:10px 2px;">Cargando…</div>';
        return;
      }
      if (!items || items.length === 0) {
        listEl.innerHTML = '<div class="muted" style="padding:10px 2px;">Sin resultados</div>';
        return;
      }

      items.forEach(function (it) {
        var b = document.createElement('button');
        b.type = 'button';
        b.className = 'qi-picker-item';
        var title = isCustomer
          ? (it.legal_name || it.name || it.rfc || '—')
          : (it.description || it.name || it.product_key || '—');
        var sub = '';
        if (isCustomer) sub = (it.rfc || '').toString();
        else {
          var price = Number(it.unit_price);
          sub = Number.isFinite(price) ? ('$' + price.toFixed(2) + ' MXN') : '';
        }
        b.innerHTML =
          '<div class="qi-picker-item__title">' + escHtml(title) + '</div>' +
          (sub ? ('<div class="qi-picker-item__sub">' + escHtml(sub) + '</div>') : '');
        b.addEventListener('click', function () {
          if (isCustomer) setSelectedCustomer(it);
          else setSelectedProduct(it);
          close();
          if (typeof onPick === 'function') onPick(it);
        });
        listEl.appendChild(b);
      });
    }

    function close() {
      closePortal(pickerModal);
    }

    openPortal(pickerModal, { returnFocusEl: opener || null });
    render('');
    search.value = '';
    search.oninput = function () { render(search.value); };
    setTimeout(function () { try { search.focus(); } catch (_) {} }, 50);
  }

  function updateModalTotals() {
    // Multi-items mode (presetLines)
    if (state.presetLines && Array.isArray(state.presetLines) && state.presetLines.length) {
      var subtotalM = 0;
      var ivaM = 0;
      state.presetLines.forEach(function (ln) {
        var pid = ln && (ln.product_id != null ? ln.product_id : ln.productId);
        if (pid == null) return;
        var prod = findProductById(pid);
        var qty = Number(ln.quantity != null ? ln.quantity : (ln.qty != null ? ln.qty : 1));
        qty = Number.isFinite(qty) && qty > 0 ? qty : 1;
        var unitPrice = (ln.unit_price != null) ? Number(ln.unit_price) : (prod ? Number(prod.unit_price) : NaN);
        unitPrice = Number.isFinite(unitPrice) ? unitPrice : 0;
        var ivaRate = prod ? Number(prod.iva_rate) : 0.16;
        ivaRate = Number.isFinite(ivaRate) ? ivaRate : 0.16;
        subtotalM += qty * unitPrice;
        ivaM += qty * unitPrice * ivaRate;
      });
      subtotalM = Math.round(subtotalM * 100) / 100;
      ivaM = Math.round(ivaM * 100) / 100;
      var totalM = Math.round((subtotalM + ivaM) * 100) / 100;
      var elSubM = document.getElementById('quickModalSubtotal');
      var elIvaM = document.getElementById('quickModalIva');
      var elTotM = document.getElementById('quickModalTotal');
      if (elSubM) elSubM.textContent = fmtMoney(subtotalM);
      if (elIvaM) elIvaM.textContent = fmtMoney(ivaM);
      if (elTotM) elTotM.textContent = fmtMoney(totalM);
      return;
    }

    if (!modalQty || !modalUnitPrice) return;
    var qty = parseNum(modalQty.value) || 0;
    var pu = parseNum(modalUnitPrice.value) || 0;
    var ivaInfo = getSelectedIvaRate();
    var ivaRate = Number.isFinite(ivaInfo.rate) ? ivaInfo.rate : 0.16;
    var isrRetRate = parseNum((modalIsrRetRate && modalIsrRetRate.value) || '');
    isrRetRate = Number.isFinite(isrRetRate) ? Math.max(0, Math.min(1, isrRetRate)) : 0;
    var ivaRetRate = parseNum((modalIvaRetRate && modalIvaRetRate.value) || '');
    ivaRetRate = Number.isFinite(ivaRetRate) ? Math.max(0, Math.min(1, ivaRetRate)) : 0;
    var subtotal = Math.round(qty * pu * 100) / 100;
    var iva = Math.round(subtotal * ivaRate * 100) / 100;
    var retIsr = Math.round(subtotal * isrRetRate * 100) / 100;
    var retIva = Math.round(iva * ivaRetRate * 100) / 100;
    var retTot = Math.round((retIsr + retIva) * 100) / 100;
    var total = Math.round((subtotal + iva - retTot) * 100) / 100;
    var elSub = document.getElementById('quickModalSubtotal');
    var elIva = document.getElementById('quickModalIva');
    var elRet = document.getElementById('quickModalRetenciones');
    var elTot = document.getElementById('quickModalTotal');
    if (elSub) elSub.textContent = fmtMoney(subtotal);
    if (elIva) elIva.textContent = fmtMoney(iva);
    if (elRet) elRet.textContent = fmtMoney(retTot);
    if (elTot) elTot.textContent = fmtMoney(total);
  }

  // Cache unit search results so we can show descriptions
  var _lastUnidadResults = [];

  var searchUnidadDebounced = debounce(function (term) {
    if (!unidadDatalist) return;
    var q = String(term || '').trim();
    if (q.length < 1) { unidadDatalist.innerHTML = ''; _lastUnidadResults = []; return; }
    httpJson('/api/catalogs/unidad?q=' + encodeURIComponent(q), { credentials: 'same-origin' }, { timeoutMs: 20000, retry: 0 })
      .then(function (res) {
        var list = (res && res.data) ? res.data : [];
        _lastUnidadResults = Array.isArray(list) ? list : [];
        unidadDatalist.innerHTML = '';
        _lastUnidadResults.forEach(function (it) {
          var opt = document.createElement('option');
          opt.value = String(it.key || '');
          opt.label = (it.key ? (String(it.key) + ' — ') : '') + String(it.label || '');
          unidadDatalist.appendChild(opt);
        });
      })
      .catch(function () {
        _lastUnidadResults = [];
        unidadDatalist.innerHTML = '';
        var opt = document.createElement('option');
        opt.value = '';
        opt.label = 'Error al buscar — intenta de nuevo';
        unidadDatalist.appendChild(opt);
      });
  }, 250);

  function updateUnitDesc() {
    if (!modalUnitDesc) return;
    var val = modalUnitKey ? String(modalUnitKey.value || '').trim().toUpperCase() : '';
    if (!val) { modalUnitDesc.textContent = ''; return; }
    var match = _lastUnidadResults.find(function (it) { return String(it.key || '').toUpperCase() === val; });
    modalUnitDesc.textContent = match ? String(match.label || '') : '';
  }

  function openQuickProdservModal(targetInputId) {
    if (!prodservModal || !prodservModalInput || !prodservModalResults) return;
    _prodservTargetInputId = targetInputId;
    prodservModal.style.display = 'block';
    prodservModal.setAttribute('aria-hidden', 'false');
    document.body.classList.add('no-scroll');
    prodservModalResults.innerHTML = '';
    prodservModalInput.value = '';
    requestAnimationFrame(function () { try { prodservModalInput.focus(); } catch (_) {} });
  }

  function closeQuickProdservModal() {
    if (!prodservModal) return;
    prodservModal.style.display = 'none';
    prodservModal.setAttribute('aria-hidden', 'true');
    document.body.classList.remove('no-scroll');
    _prodservTargetInputId = null;
    if (_prodservAbort) { try { _prodservAbort.abort(); } catch (_) {} _prodservAbort = null; }
  }

  function searchQuickProdserv(term) {
    if (!prodservModalResults) return;
    var q = String(term || '').trim();
    if (q.length < 2) { prodservModalResults.innerHTML = ''; return; }
    if (_prodservAbort) { try { _prodservAbort.abort(); } catch (_) {} }
    _prodservAbort = new AbortController();
    var signal = _prodservAbort.signal;
    prodservModalResults.innerHTML = '<div class="muted" style="padding:12px;">Buscando…</div>';
    var url = '/api/catalogs/prodserv?q=' + encodeURIComponent(q);
    var p = window.portalCatalogGetJson
      ? window.portalCatalogGetJson(url, { signal: signal })
      : httpJson(url, { credentials: 'same-origin', signal: signal }, { timeoutMs: 20000, retry: 0 }).then(function (r) { return r.data; });

    Promise.resolve(p)
      .then(function (list) {
        if (signal.aborted) return;
        var items = Array.isArray(list) ? list : [];
        if (items.length === 0) {
          prodservModalResults.innerHTML = '<div class="muted" style="padding:12px;">Sin resultados</div>';
          return;
        }
        prodservModalResults.innerHTML = '';
        items.forEach(function (it) {
          var b = document.createElement('button');
          b.type = 'button';
          b.className = 'result-row';
          b.innerHTML = '<span class="result-code">' + String(it.key || '') + '</span><span class="result-desc">' + String(it.label || '') + '</span>';
          b.addEventListener('click', function () {
            var key = String(it.key || '').trim();
            var desc = String(it.label || '').trim();
            if (!key) return;
            var target = _prodservTargetInputId ? document.getElementById(_prodservTargetInputId) : null;
            if (target) {
              target.value = key;
              target.dispatchEvent(new Event('input', { bubbles: true }));
            }
            // Show description label next to the ProdServ input
            if (_prodservTargetInputId === 'quickModalProductKey' && modalProdservDesc) {
              modalProdservDesc.textContent = desc;
            }
            closeQuickProdservModal();
          });
          prodservModalResults.appendChild(b);
        });
      })
      .catch(function () {
        if (signal.aborted) return;
        prodservModalResults.innerHTML = '<div class="muted" style="padding:12px;">No se pudo buscar. Intenta de nuevo.</div>';
      });
  }

  function openQuickModalOrThrow() {
    if (!modal) throw new Error('Modal no disponible');
    var cust = state.currentCustomerId ? findCustomerById(state.currentCustomerId) : null;
    var prod = state.currentProductId ? findProductById(state.currentProductId) : null;
    var hasPresetLines = !!(state.presetLines && state.presetLines.length);
    if (!cust && !prod && !hasPresetLines) throw new Error('Selecciona al menos un cliente o producto.');

    window.__quickCurrentIva = prod ? (parseNum(prod.iva_rate) || 0.16) : 0.16;
    var elRfc = document.getElementById('quickModalCustomerRfc');
    if (elRfc) elRfc.textContent = (cust && cust.rfc) ? ('RFC ' + cust.rfc) : '';

    // Update "Cambiar" button labels based on state
    var changeCustBtn = document.getElementById('quickModalChangeCustomer');
    var changeProdBtn = document.getElementById('quickModalChangeProduct');
    if (changeCustBtn) changeCustBtn.textContent = cust ? 'Cambiar' : 'Buscar cliente';
    if (changeProdBtn) changeProdBtn.textContent = prod ? 'Cambiar' : 'Buscar producto';

    if (modalCustomerName) modalCustomerName.value = cust ? (cust.legal_name || '').trim() : '';
    if (modalCustomerZip) modalCustomerZip.value = cust ? (cust.zip || '').trim() : '';
    if (modalCustomerTaxSystem) modalCustomerTaxSystem.value = cust ? (cust.tax_system || '').trim() : '';
    if (modalCustomerEmail) modalCustomerEmail.value = cust ? (cust.email || '').trim() : '';
    if (modalAutoEmail) modalAutoEmail.checked = false;

    if (hasPresetLines) {
      if (modalItemsSummary) {
        var lines = state.presetLines.slice(0, 50);
        var html = '<div class="muted u-text-12 u-mb-2">Se facturarán ' + state.presetLines.length + ' conceptos:</div>';
        html += '<div class="qi-items-summary__list">';
        lines.forEach(function (ln) {
          var pid = ln && (ln.product_id != null ? ln.product_id : ln.productId);
          var prod = pid != null ? findProductById(pid) : null;
          var qty = Number(ln.quantity != null ? ln.quantity : (ln.qty != null ? ln.qty : 1));
          qty = Number.isFinite(qty) && qty > 0 ? qty : 1;
          var title = prod ? (prod.description || prod.product_key || ('Producto ' + pid)) : ('Producto ' + pid);
          html += '<div class="qi-items-summary__row"><span class="qi-items-summary__qty">' + qty + '×</span><span class="qi-items-summary__title">' + String(title).replace(/</g, '&lt;').replace(/>/g, '&gt;') + '</span></div>';
        });
        if (state.presetLines.length > lines.length) html += '<div class="muted u-text-12 u-mt-2">+' + (state.presetLines.length - lines.length) + ' más…</div>';
        html += '</div>';
        modalItemsSummary.innerHTML = html;
        modalItemsSummary.hidden = false;
      }
      if (modalSingleConcept) modalSingleConcept.hidden = true;
    } else {
      if (modalItemsSummary) { modalItemsSummary.hidden = true; modalItemsSummary.innerHTML = ''; }
      if (modalSingleConcept) modalSingleConcept.hidden = false;
      if (modalProductDesc) modalProductDesc.value = prod ? (prod.description || '').trim() : '';
      if (modalProductKey) modalProductKey.value = prod ? (prod.product_key || '').trim() : '';
      if (modalUnitKey) modalUnitKey.value = prod ? (prod.unit_key || 'E48').trim() : '';
      if (modalQty) modalQty.value = '1';
      if (modalUnitPrice) {
        modalUnitPrice.value = prod ? String(prod.unit_price != null ? prod.unit_price : '') : '';
        if (prod) formatMoneyInput(modalUnitPrice);
      }
    }

    if (modalIvaRate && !(state.presetLines && state.presetLines.length)) {
      var iva = parseNum(window.__quickCurrentIva);
      if (Math.abs(iva - 0.16) < 0.0001) modalIvaRate.value = '0.16';
      else if (Math.abs(iva - 0.08) < 0.0001) modalIvaRate.value = '0.08';
      else if (Math.abs(iva - 0.0) < 0.0001) modalIvaRate.value = '0.00';
      else modalIvaRate.value = '0.16';
    }

    if (modalIsrRetRate) modalIsrRetRate.value = '0';
    if (modalIvaRetRate) modalIvaRetRate.value = '0';

    // Reset description labels
    if (modalProdservDesc) modalProdservDesc.textContent = '';
    if (modalUnitDesc) modalUnitDesc.textContent = '';

    var defs = state.defaults || window.__quickInvoiceDefaults || null;
    if (modalCurrency) modalCurrency.value = (defs && defs.currency) ? String(defs.currency) : 'MXN';
    // Exchange rate: show/hide based on currency
    var currVal = modalCurrency ? String(modalCurrency.value || '').toUpperCase() : 'MXN';
    if (modalExchangeRateWrap) modalExchangeRateWrap.hidden = (currVal === 'MXN');
    if (modalExchangeRate) modalExchangeRate.value = (defs && defs.exchange_rate != null) ? String(defs.exchange_rate) : '1.0';
    if (modalCfdiUse) modalCfdiUse.value = (defs && defs.uso_cfdi) ? String(defs.uso_cfdi) : 'G03';
    if (modalPaymentForm) modalPaymentForm.value = (defs && defs.payment_form) ? String(defs.payment_form) : '03';
    if (modalPaymentMethod) modalPaymentMethod.value = (defs && defs.payment_method) ? String(defs.payment_method) : 'PUE';

    if (modalError) {
      modalError.hidden = true;
      modalError.textContent = '';
    }
    renderPlanUsageBadge();
    updateModalTotals();

    openPortal(modal, {
      returnFocusEl: homeBtn || null,
      onClose: function () {
        state.presetLines = null;
        if (modalItemsSummary) { modalItemsSummary.hidden = true; modalItemsSummary.innerHTML = ''; }
        if (modalSingleConcept) modalSingleConcept.hidden = false;
      }
    });
    setTimeout(function () { try { (modalQty || document.getElementById('quickInvoiceModalPanel')).focus(); } catch (_) {} }, 80);
  }

  function closeQuickModal() {
    if (!modal) return;
    closePortal(modal);
  }

  function open(options) {
    var opts = options || {};
    // Replacement mode
    state.replaces_uuid = opts.replaces_uuid || null;
    state.prefillCfdiUse = opts.prefillCfdiUse || null;
    state.prefillPaymentForm = opts.prefillPaymentForm || null;
    state.prefillPaymentMethod = opts.prefillPaymentMethod || null;
    state.prefillCurrency = opts.prefillCurrency || null;

    return Promise.all([ensureBootstrap(false), ensureCatalogs()])
      .then(function () {
        // Preset lines (multi-product invoice)
        if (Array.isArray(opts.presetLines) && opts.presetLines.length) {
          state.presetLines = opts.presetLines
            .filter(function (x) { return x && (x.product_id != null || x.productId != null); })
            .map(function (x) {
              return {
                product_id: (x.product_id != null ? Number(x.product_id) : Number(x.productId)),
                quantity: Number(x.quantity != null ? x.quantity : (x.qty != null ? x.qty : 1)),
              };
            })
            .filter(function (x) { return Number.isFinite(x.product_id) && x.product_id > 0; });
          if (state.presetLines.length && !opts.preselectedProductId) {
            setSelectedProduct(state.presetLines[0].product_id);
          }
        } else {
          state.presetLines = null;
        }
        if (opts.preselectedCustomerId != null) setSelectedCustomer(opts.preselectedCustomerId);
        if (opts.preselectedCustomerRfc) {
          var match = findCustomerByRfc(opts.preselectedCustomerRfc);
          if (match) setSelectedCustomer(match);
        }
        if (opts.preselectedProductId != null) setSelectedProduct(opts.preselectedProductId);

        // Pre-fill form fields for replacement mode
        if (state.prefillCfdiUse && modalCfdiUse) modalCfdiUse.value = state.prefillCfdiUse;
        if (state.prefillPaymentForm && modalPaymentForm) modalPaymentForm.value = state.prefillPaymentForm;
        if (state.prefillPaymentMethod && modalPaymentMethod) modalPaymentMethod.value = state.prefillPaymentMethod;
        if (state.prefillCurrency && modalCurrency) modalCurrency.value = state.prefillCurrency;

        // Update submit button text for replacement mode
        if (modalSubmit) {
          modalSubmit.textContent = state.replaces_uuid ? 'Timbrar y cancelar original' : 'Timbrar factura';
        }

        // Si allowPartial, abrir modal directamente con lo que haya.
        // Si no, pedir lo que falte con picker.
        if (!opts.allowPartial) {
          if (!state.currentCustomerId) {
            state._pendingOpenAfterPick = function () { open(opts); };
            openPicker('customer', function () {
              var fn = state._pendingOpenAfterPick;
              state._pendingOpenAfterPick = null;
              if (typeof fn === 'function') fn();
            });
            return;
          }
          if (!state.currentProductId) {
            state._pendingOpenAfterPick = function () { open(opts); };
            openPicker('product', function () {
              var fn = state._pendingOpenAfterPick;
              state._pendingOpenAfterPick = null;
              if (typeof fn === 'function') fn();
            });
            return;
          }
        }

        openQuickModalOrThrow();
      })
      .catch(function (e) {
        toast({ type: 'danger', title: 'Error', message: (e && e.message) || 'No se pudo abrir la factura rápida.' });
      });
  }

  function createQsel(containerId, hiddenId, options) {
    var container = document.getElementById(containerId);
    var hidden = document.getElementById(hiddenId);
    if (!container || !hidden) return;
    var input = container.querySelector('.qsel-input');
    var menu = container.querySelector('.qsel-menu');
    var getList = options.getList || function () { return options.list || []; };
    var getLabel = options.getLabel;
    var getValue = options.getValue;
    var filterFn = options.filterFn;
    var onSelect = options.onSelect;

    var selectedIndex = -1;
    var openMenu = false;

    function renderItems(items) {
      if (!menu) return;
      var list = items || getList();
      menu.innerHTML = '';
      if (!list || list.length === 0) {
        menu.innerHTML = '<div class="qsel-item qsel-item--empty">Sin resultados</div>';
        menu.hidden = false;
        return;
      }
      list.forEach(function (item, i) {
        var div = document.createElement('div');
        div.className = 'qsel-item';
        div.setAttribute('data-index', i);
        div.setAttribute('data-value', String(getValue(item)));
        div.textContent = getLabel(item);
        div.role = 'option';
        div.id = containerId + '-opt-' + i;
        menu.appendChild(div);
      });
      menu.hidden = false;
      selectedIndex = 0;
      highlightItem(0);
    }

    function highlightItem(index) {
      var items = menu.querySelectorAll('.qsel-item:not(.qsel-item--empty)');
      items.forEach(function (el, i) {
        el.classList.toggle('qsel-item--active', i === index);
        el.setAttribute('aria-selected', i === index ? 'true' : 'false');
      });
      if (items[index]) items[index].scrollIntoView({ block: 'nearest' });
    }

    function closeMenu() {
      menu.hidden = true;
      openMenu = false;
      selectedIndex = -1;
    }

    function selectByIndex(index) {
      var items = menu.querySelectorAll('.qsel-item:not(.qsel-item--empty)');
      var itemEl = items[index];
      if (!itemEl) return;
      var val = itemEl.getAttribute('data-value');
      var list = getList();
      var item = list[parseInt(itemEl.getAttribute('data-index'), 10)];
      if (item && val !== undefined) {
        hidden.value = val;
        if (input) input.value = getLabel(item);
        closeMenu();
        if (typeof onSelect === 'function') onSelect(item);
        hidden.dispatchEvent(new Event('change', { bubbles: true }));
      }
    }

    if (input) {
      input.addEventListener('focus', function () {
        var list = getList();
        if (list.length) renderItems(list);
        openMenu = true;
      });
      input.addEventListener('input', function () {
        var list = getList();
        var q = (input.value || '').trim().toLowerCase();
        var filtered = q ? list.filter(function (item) { return filterFn(item, q); }) : list;
        renderItems(filtered);
        openMenu = true;
      });
      input.addEventListener('keydown', function (e) {
        var list = getList();
        if (!openMenu || menu.hidden) {
          if (e.key === 'ArrowDown' || e.key === 'Enter') {
            if (list.length) { renderItems(list); openMenu = true; }
          }
          return;
        }
        var items = menu.querySelectorAll('.qsel-item:not(.qsel-item--empty)');
        if (e.key === 'Escape') {
          closeMenu();
          input.blur();
          e.preventDefault();
          return;
        }
        if (e.key === 'ArrowDown') {
          selectedIndex = Math.min(selectedIndex + 1, items.length - 1);
          highlightItem(selectedIndex);
          e.preventDefault();
          return;
        }
        if (e.key === 'ArrowUp') {
          selectedIndex = Math.max(selectedIndex - 1, 0);
          highlightItem(selectedIndex);
          e.preventDefault();
          return;
        }
        if (e.key === 'Enter' && items[selectedIndex]) {
          selectByIndex(selectedIndex);
          e.preventDefault();
        }
      });
    }

    if (menu) {
      menu.addEventListener('click', function (e) {
        var item = e.target.closest('.qsel-item:not(.qsel-item--empty)');
        if (item) selectByIndex(parseInt(item.getAttribute('data-index'), 10));
      });
    }

    document.addEventListener('click', function (e) {
      if (openMenu && container && !container.contains(e.target)) closeMenu();
    });
  }

  function initHomeQselsIfPresent() {
    if (!customerHidden || !productHidden || !qselCustomer || !qselProduct) return;

    function setLoading(loading) {
      [qselCustomer, qselProduct].forEach(function (el) {
        var inp = el && el.querySelector('.qsel-input');
        if (inp) inp.placeholder = loading ? 'Cargando…' : (el === qselCustomer ? 'Buscar cliente por nombre o RFC…' : 'Buscar producto…');
      });
    }

    setLoading(true);
    ensureBootstrap(false)
      .then(function () {
        setLoading(false);
        hideInlineError(qselCustomer);
        hideInlineError(qselProduct);

        createQsel('qselCustomer', 'quickCustomer', {
          getList: function () { return state.customers || []; },
          getLabel: function (c) { return (c.legal_name || c.name || c.rfc || '—').trim(); },
          getValue: function (c) { return c.id; },
          filterFn: function (c, q) {
            var name = (c.legal_name || c.name || '').toLowerCase();
            var rfc = (c.rfc || '').toLowerCase();
            return name.indexOf(q) !== -1 || rfc.indexOf(q) !== -1;
          },
          onSelect: function (c) { setSelectedCustomer(c); },
        });

        createQsel('qselProduct', 'quickProduct', {
          getList: function () { return state.products || []; },
          getLabel: function (p) { return (p.description || p.name || p.product_key || '—').trim(); },
          getValue: function (p) { return p.id; },
          filterFn: function (p, q) {
            var desc = (p.description || p.name || '').toLowerCase();
            var key = (p.product_key || p.prodserv || '').toLowerCase();
            return desc.indexOf(q) !== -1 || key.indexOf(q) !== -1;
          },
          onSelect: function (p) { setSelectedProduct(p); },
        });

        setHomeBtnState();
      })
      .catch(function () {
        setLoading(false);
        showInlineError(qselCustomer, 'No se pudo cargar. Revisa tu conexión e intenta de nuevo.');
        showInlineError(qselProduct, 'No se pudo cargar. Revisa tu conexión e intenta de nuevo.');
      });
  }

  function openAddCustomerModal() {
    if (!addCustomerModal) return;
    if (addCustomerError) { addCustomerError.hidden = true; addCustomerError.textContent = ''; }
    if (addCustomerRfc) addCustomerRfc.value = '';
    if (addCustomerName) addCustomerName.value = '';
    if (addCustomerZip) addCustomerZip.value = '';
    if (addCustomerEmail) addCustomerEmail.value = '';
    if (addCustomerAlias) addCustomerAlias.value = '';
    if (addCustomerTaxSystem) addCustomerTaxSystem.value = '';
    if (addCustomerUsoCfdi) addCustomerUsoCfdi.value = (state.defaults && state.defaults.uso_cfdi) ? String(state.defaults.uso_cfdi) : 'G03';
    openPortal(addCustomerModal, {
      returnFocusEl: addCustomerBtn || null,
      onClose: function () {
        if (addCustomerError) { addCustomerError.hidden = true; addCustomerError.textContent = ''; }
      }
    });
    setTimeout(function () { try { if (addCustomerRfc) addCustomerRfc.focus(); } catch (_) {} }, 80);
  }

  function closeAddCustomerModal() {
    if (!addCustomerModal) return;
    closePortal(addCustomerModal);
  }

  function openAddProductModal() {
    if (!addProductModal) return;
    if (addProductError) { addProductError.hidden = true; addProductError.textContent = ''; }
    if (addProductDesc) addProductDesc.value = '';
    if (addProductKey) addProductKey.value = '';
    if (addProductUnitKey) addProductUnitKey.value = 'E48';
    if (addProductUnitPrice) addProductUnitPrice.value = '';
    if (addProductIvaRate) addProductIvaRate.value = '0.16';
    openPortal(addProductModal, {
      returnFocusEl: addProductBtn || null,
      onClose: function () {
        if (addProductError) { addProductError.hidden = true; addProductError.textContent = ''; }
      }
    });
    setTimeout(function () { try { if (addProductDesc) addProductDesc.focus(); } catch (_) {} }, 80);
  }

  function closeAddProductModal() {
    if (!addProductModal) return;
    closePortal(addProductModal);
  }

  function bindGlobalEvents() {
    // Pickers (lupita)
    var openC = document.getElementById('qiOpenClientPicker');
    var openP = document.getElementById('qiOpenProductPicker');
    if (openC) openC.addEventListener('click', function (e) { e.preventDefault(); ensureBootstrap(false).then(function(){ openPicker('customer'); }); });
    if (openP) openP.addEventListener('click', function (e) { e.preventDefault(); ensureBootstrap(false).then(function(){ openPicker('product'); }); });

    // Home button (si existe)
    if (homeBtn) {
      homeBtn.addEventListener('click', function (e) {
        e.preventDefault();
        var cId = customerHidden ? String(customerHidden.value || '') : '';
        var pId = productHidden ? String(productHidden.value || '') : '';
        open({ preselectedCustomerId: cId || null, preselectedProductId: pId || null });
      });
    }

    if (customerHidden) customerHidden.addEventListener('change', setHomeBtnState);
    if (productHidden) productHidden.addEventListener('change', setHomeBtnState);

    [modalQty, modalUnitPrice, modalIvaRate, modalIsrRetRate, modalIvaRetRate].forEach(function (el) {
      if (el) el.addEventListener('input', updateModalTotals);
    });
    if (modalUnitPrice) modalUnitPrice.addEventListener('blur', function () { formatMoneyInput(modalUnitPrice); updateModalTotals(); });
    if (modalQty) modalQty.addEventListener('blur', function () { modalQty.value = String(parseNum(modalQty.value) || 0); updateModalTotals(); });
    if (modalUnitKey) {
      modalUnitKey.addEventListener('input', function () { searchUnidadDebounced(modalUnitKey.value); });
      modalUnitKey.addEventListener('change', updateUnitDesc);
    }
    if (modalProdservBtn) modalProdservBtn.addEventListener('click', function () { openQuickProdservModal('quickModalProductKey'); });

    // Show/hide exchange rate field based on currency
    if (modalCurrency) {
      modalCurrency.addEventListener('change', function () {
        var isMXN = String(modalCurrency.value || '').toUpperCase() === 'MXN';
        if (modalExchangeRateWrap) modalExchangeRateWrap.hidden = isMXN;
        if (isMXN && modalExchangeRate) modalExchangeRate.value = '1.0';
      });
    }

    // ProdServ modal events
    if (prodservModal) {
      prodservModal.addEventListener('click', function (e) {
        var t = e.target;
        if (t && t.getAttribute && t.getAttribute('data-close') === '1') closeQuickProdservModal();
        if (t && t.closest && t.closest('[data-close="1"]')) closeQuickProdservModal();
        if (t && t.classList && t.classList.contains('form-modal__backdrop')) closeQuickProdservModal();
      });
      document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape' && prodservModal.style.display === 'block') closeQuickProdservModal();
      });
    }
    if (prodservModalInput) prodservModalInput.addEventListener('input', debounce(function () { searchQuickProdserv(prodservModalInput.value); }, 250));

    // "Cambiar" / "Buscar" buttons inside the quick invoice modal
    var changeCustBtn = document.getElementById('quickModalChangeCustomer');
    var changeProdBtn = document.getElementById('quickModalChangeProduct');
    if (changeCustBtn) changeCustBtn.addEventListener('click', function (e) {
      e.preventDefault();
      ensureBootstrap(false).then(function () {
        openPicker('customer', function () {
          // Refresh modal fields with newly selected customer
          var c = state.currentCustomerId ? findCustomerById(state.currentCustomerId) : null;
          if (!c) return;
          var elRfc = document.getElementById('quickModalCustomerRfc');
          if (elRfc) elRfc.textContent = c.rfc ? ('RFC ' + c.rfc) : '';
          if (modalCustomerName) modalCustomerName.value = (c.legal_name || '').trim();
          if (modalCustomerZip) modalCustomerZip.value = (c.zip || '').trim();
          if (modalCustomerTaxSystem) modalCustomerTaxSystem.value = (c.tax_system || '').trim();
          if (modalCustomerEmail) modalCustomerEmail.value = (c.email || '').trim();
          changeCustBtn.textContent = 'Cambiar';
          if (modalError) modalError.hidden = true;
        });
      });
    });
    if (changeProdBtn) changeProdBtn.addEventListener('click', function (e) {
      e.preventDefault();
      ensureBootstrap(false).then(function () {
        openPicker('product', function () {
          // Refresh modal fields with newly selected product
          var p = state.currentProductId ? findProductById(state.currentProductId) : null;
          if (!p) return;
          window.__quickCurrentIva = parseNum(p.iva_rate) || 0.16;
          if (modalProductDesc) modalProductDesc.value = (p.description || '').trim();
          if (modalProductKey) modalProductKey.value = (p.product_key || '').trim();
          if (modalUnitKey) modalUnitKey.value = (p.unit_key || 'E48').trim();
          if (modalUnitPrice) { modalUnitPrice.value = String(p.unit_price != null ? p.unit_price : ''); formatMoneyInput(modalUnitPrice); }
          var iva = parseNum(window.__quickCurrentIva);
          if (modalIvaRate) {
            if (Math.abs(iva - 0.16) < 0.0001) modalIvaRate.value = '0.16';
            else if (Math.abs(iva - 0.08) < 0.0001) modalIvaRate.value = '0.08';
            else if (Math.abs(iva - 0.0) < 0.0001) modalIvaRate.value = '0.00';
            else modalIvaRate.value = '0.16';
          }
          updateModalTotals();
          changeProdBtn.textContent = 'Cambiar';
          if (modalError) modalError.hidden = true;
        });
      });
    });

    // Add customer/product open
    if (addCustomerBtn) addCustomerBtn.addEventListener('click', function (e) { e.preventDefault(); openAddCustomerModal(); });
    if (addProductBtn) addProductBtn.addEventListener('click', function (e) { e.preventDefault(); openAddProductModal(); });
    if (addProductProdservBtn) addProductProdservBtn.addEventListener('click', function () { openQuickProdservModal('quickProductKey'); });

    // Save customer
    if (addCustomerSave) addCustomerSave.addEventListener('click', function () {
      if (state._savingCustomer) return;
      var rfc = (addCustomerRfc && addCustomerRfc.value || '').trim().toUpperCase();
      var legalName = (addCustomerName && addCustomerName.value || '').trim();
      if (!rfc || !legalName) {
        if (addCustomerError) { addCustomerError.textContent = 'RFC y Razón social son obligatorios.'; addCustomerError.hidden = false; }
        return;
      }
      state._savingCustomer = true;
      var zip = (addCustomerZip && addCustomerZip.value || '').trim();
      var taxSystem = (addCustomerTaxSystem && addCustomerTaxSystem.value || '').trim();
      var usoCfdi = (addCustomerUsoCfdi && addCustomerUsoCfdi.value || '').trim();
      var email = (addCustomerEmail && addCustomerEmail.value || '').trim() || null;
      var alias = (addCustomerAlias && addCustomerAlias.value || '').trim() || null;
      if (addCustomerError) { addCustomerError.hidden = true; addCustomerError.textContent = ''; }
      addCustomerSave.disabled = true;
      var csrf = document.querySelector('meta[name="csrf-token"]') && document.querySelector('meta[name="csrf-token"]').getAttribute('content');
      var headers = { 'Content-Type': 'application/json' };
      if (csrf) headers['X-CSRF-Token'] = csrf;
      httpJson('/api/customers/create', { method: 'POST', credentials: 'same-origin', headers: headers, body: JSON.stringify({ rfc: rfc, legal_name: legalName, zip: zip, tax_system: taxSystem, uso_cfdi_default: usoCfdi, email: email, alias: alias }) }, { timeoutMs: 30000, retry: 0 })
        .then(function (res) {
          state._savingCustomer = false;
          addCustomerSave.disabled = false;
          if (res && res.ok && res.data && res.data.ok) {
            closeAddCustomerModal();
            window.__quickAfterCustomerRfc = rfc;
            ensureBootstrap(true);
            toast({ type: 'success', title: 'Cliente guardado', message: 'Se añadió ' + rfc });
            return;
          }
          var detail = (res && res.data && res.data.detail) ? (typeof res.data.detail === 'string' ? res.data.detail : JSON.stringify(res.data.detail)) : '';
          if (addCustomerError) { addCustomerError.textContent = detail || (res && res.detail) || 'No se pudo guardar el cliente.'; addCustomerError.hidden = false; }
        })
        .catch(function (err) {
          state._savingCustomer = false;
          addCustomerSave.disabled = false;
          if (addCustomerError) { addCustomerError.textContent = (err && err.message) || 'Error de conexión. Intenta de nuevo.'; addCustomerError.hidden = false; }
        });
    });

    // Save product
    if (addProductSave) addProductSave.addEventListener('click', function () {
      if (state._savingProduct) return;
      var desc = (addProductDesc && addProductDesc.value || '').trim();
      var prodKey = (addProductKey && addProductKey.value || '').trim();
      var unitKey = (addProductUnitKey && addProductUnitKey.value || '').trim() || 'E48';
      var unitPrice = parseNum(addProductUnitPrice && addProductUnitPrice.value);
      var iva = (addProductIvaRate && addProductIvaRate.value) ? String(addProductIvaRate.value) : '0.16';
      if (!desc || !prodKey || !Number.isFinite(unitPrice)) {
        if (addProductError) { addProductError.textContent = 'Descripción, ProdServ y precio son obligatorios.'; addProductError.hidden = false; }
        return;
      }
      if (addProductError) { addProductError.hidden = true; addProductError.textContent = ''; }
      state._savingProduct = true;
      addProductSave.disabled = true;
      var csrf = document.querySelector('meta[name="csrf-token"]') && document.querySelector('meta[name="csrf-token"]').getAttribute('content');
      var headers = { 'Content-Type': 'application/json' };
      if (csrf) headers['X-CSRF-Token'] = csrf;
      httpJson('/api/products/create', { method: 'POST', credentials: 'same-origin', headers: headers, body: JSON.stringify({ description: desc, product_key: prodKey, unit_key: unitKey, unit_price: unitPrice, iva_rate: iva }) }, { timeoutMs: 30000, retry: 0 })
        .then(function (res) {
          state._savingProduct = false;
          addProductSave.disabled = false;
          if (res && res.ok && res.data && res.data.ok && res.data.id != null) {
            closeAddProductModal();
            window.__quickAfterProductId = res.data.id;
            ensureBootstrap(true);
            toast({ type: 'success', title: 'Producto guardado', message: 'Se añadió al catálogo.' });
            return;
          }
          var detail = (res && res.data && res.data.detail) ? (typeof res.data.detail === 'string' ? res.data.detail : JSON.stringify(res.data.detail)) : '';
          if (addProductError) { addProductError.textContent = detail || (res && res.detail) || 'No se pudo guardar el producto.'; addProductError.hidden = false; }
        })
        .catch(function (err) {
          state._savingProduct = false;
          addProductSave.disabled = false;
          if (addProductError) { addProductError.textContent = (err && err.message) || 'Error de conexión. Intenta de nuevo.'; addProductError.hidden = false; }
        });
    });

    // Submit invoice
    if (modalSubmit) modalSubmit.addEventListener('click', function () {
      if (state._submitting) return;
      var customerId = state.currentCustomerId;
      var productId = state.currentProductId;
      if (!customerId) {
        if (modalError) { modalError.textContent = 'Selecciona un cliente con el botón "Buscar cliente".'; modalError.hidden = false; }
        return;
      }
      var isMulti = !!(state.presetLines && state.presetLines.length);
      var qty = null;
      var unitPrice = null;
      if (!isMulti) {
        if (!productId) {
          if (modalError) { modalError.textContent = 'Selecciona un producto con el botón "Buscar producto".'; modalError.hidden = false; }
          return;
        }
        qty = parseNum(modalQty && modalQty.value);
        unitPrice = parseNum(modalUnitPrice && modalUnitPrice.value);
        if (!qty || qty <= 0) {
          if (modalError) { modalError.textContent = 'Ingresa una cantidad válida.'; modalError.hidden = false; }
          return;
        }
        if (!Number.isFinite(unitPrice) || unitPrice < 0) {
          if (modalError) { modalError.textContent = 'Ingresa un precio unitario válido.'; modalError.hidden = false; }
          return;
        }
      }
      if (modalError) { modalError.hidden = true; modalError.textContent = ''; }

      state._submitting = true;
      var submitLabel = modalSubmit.textContent;
      modalSubmit.disabled = true;
      modalSubmit.textContent = 'Timbrando…';

      var _submitTimeout = setTimeout(function () {
        state._submitting = false;
        modalSubmit.disabled = false;
        modalSubmit.textContent = submitLabel;
        toast({ type: 'warning', title: 'La operación tardó demasiado. Intenta de nuevo.' });
      }, 65000);

      var custName = (modalCustomerName && modalCustomerName.value || '').trim();
      var custZip = (modalCustomerZip && modalCustomerZip.value || '').trim();
      var custTaxSystem = (modalCustomerTaxSystem && modalCustomerTaxSystem.value || '').trim();
      var custEmail = (modalCustomerEmail && modalCustomerEmail.value || '').trim();
      var autoEmail = !!(modalAutoEmail && modalAutoEmail.checked);

      var desc = (modalProductDesc && modalProductDesc.value || '').trim();
      var productKey = (modalProductKey && modalProductKey.value || '').trim();
      var unitKey = (modalUnitKey && modalUnitKey.value || '').trim();

      var currency = (modalCurrency && modalCurrency.value || 'MXN').trim();
      var exchangeRate = parseNum(modalExchangeRate && modalExchangeRate.value);
      if (!Number.isFinite(exchangeRate) || exchangeRate <= 0) exchangeRate = 1.0;
      var usoCfdi = (modalCfdiUse && modalCfdiUse.value || '').trim();
      var paymentForm = (modalPaymentForm && modalPaymentForm.value || '').trim();
      var paymentMethod = (modalPaymentMethod && modalPaymentMethod.value || 'PUE').trim();

      var ivaInfo = getSelectedIvaRate();
      var ivaRate = ivaInfo.exento ? 'EXENTO' : String(ivaInfo.rate);

      var csrf = document.querySelector('meta[name="csrf-token"]') && document.querySelector('meta[name="csrf-token"]').getAttribute('content');
      var headers = { 'Content-Type': 'application/json' };
      if (csrf) headers['X-CSRF-Token'] = csrf;

      var payload = {
        customer_id: customerId,
        customer_name: custName,
        customer_zip: custZip,
        customer_tax_system: custTaxSystem,
        customer_email: custEmail,
        auto_email: autoEmail,
        currency: currency,
        exchange_rate: exchangeRate,
        uso_cfdi: usoCfdi,
        payment_form: paymentForm,
        payment_method: paymentMethod
      };
      // Replacement mode: include replaces_uuid so backend adds related_documents + auto-cancels
      if (state.replaces_uuid) {
        payload.replaces_uuid = state.replaces_uuid;
      }
      if (isMulti) {
        payload.items = state.presetLines.map(function (ln) {
          return { product_id: ln.product_id, quantity: ln.quantity || 1 };
        });
      } else {
        payload.product_id = productId;
        payload.quantity = qty;
        payload.unit_price = unitPrice;
        payload.iva_rate = ivaRate;
        payload.description = desc;
        payload.product_key = productKey;
        payload.unit_key = unitKey;
      }

      var isReplacement = !!state.replaces_uuid;
      httpJson('/api/invoices/quick', { method: 'POST', credentials: 'same-origin', headers: headers, body: JSON.stringify(payload) }, { timeoutMs: 60000, retry: 0 })
        .then(function (res) {
          clearTimeout(_submitTimeout);
          state._submitting = false;
          modalSubmit.disabled = false;
          modalSubmit.textContent = submitLabel;
          if (res && res.ok && res.data && res.data.ok) {
            closeQuickModal();
            // Reset replacement state
            state.replaces_uuid = null;
            var successTitle = isReplacement ? 'Factura emitida — original cancelada' : 'Factura timbrada';
            var successMsg = 'Total ' + fmtMoney(res.data.total || 0) + '.';
            if (isReplacement) {
              var cr = res.data.cancel_result;
              if (cr === 'pending') successMsg += ' La cancelación de la original está pendiente de aceptación.';
              else if (cr === 'error') successMsg += ' No se pudo cancelar la original automáticamente.';
              else successMsg += ' La factura original fue cancelada.';
            } else {
              successMsg += ' Puedes descargar XML/PDF o verla en emitidas.';
            }
            if (window.uiSuccessOverlay) {
              window.uiSuccessOverlay({
                title: successTitle,
                message: successMsg,
                actions: [{ label: 'Ver facturas emitidas', href: '/portal/facturas?tab=issued' }],
                autoDismiss: 6000
              });
            } else {
              toast({ type: 'success', title: successTitle, message: successMsg });
            }
            return;
          }
          var detail = (res && res.data && res.data.detail) ? (typeof res.data.detail === 'string' ? res.data.detail : JSON.stringify(res.data.detail)) : '';
          if (modalError) { modalError.textContent = detail || (res && res.detail) || 'No se pudo timbrar. Intenta de nuevo.'; modalError.hidden = false; }
        })
        .catch(function (err) {
          clearTimeout(_submitTimeout);
          state._submitting = false;
          modalSubmit.disabled = false;
          modalSubmit.textContent = submitLabel;
          if (modalError) { modalError.textContent = (err && err.message) || 'Error de conexión. Intenta de nuevo.'; modalError.hidden = false; }
        });
    });
  }

  // Exponer API
  window.QuickInvoice = window.QuickInvoice || {};
  window.QuickInvoice.open = open;
  window.QuickInvoice.setSelectedCustomer = setSelectedCustomer;
  window.QuickInvoice.setSelectedProduct = setSelectedProduct;
  window.QuickInvoice.pickCustomer = function () {
    return ensureBootstrap(false).then(function () {
      return new Promise(function (resolve) { openPicker('customer', resolve); });
    });
  };
  window.QuickInvoice.pickProduct = function () {
    return ensureBootstrap(false).then(function () {
      return new Promise(function (resolve) { openPicker('product', resolve); });
    });
  };

  // Legacy contract
  window.quickInvoiceReload = function () { return ensureBootstrap(true); };

  // Boot
  function boot() {
    // Catálogos ayudan al modal aunque no se abra en ese momento.
    ensureCatalogs();
    ensureBootstrap(false);
    initHomeQselsIfPresent();
    bindGlobalEvents();
    setHomeBtnState();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})();
