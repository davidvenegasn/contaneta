/**
 * Movement Modals — two separate modals + activity popup.
 *   #addMovementModal — manual movement (gasto/ingreso)
 *   #addInvoiceModal  — foreign invoice
 *   #activityModal    — recent activity popup
 */
(function() {
  'use strict';

  var today = new Date().toISOString().slice(0, 10);

  function getCSRF() {
    var m = document.querySelector('meta[name="csrf-token"]');
    return m ? m.content : '';
  }
  function formatMoney(n) {
    if (n == null) return '';
    return '$' + Number(n).toLocaleString('es-MX', {minimumFractionDigits:2, maximumFractionDigits:2});
  }

  // ── Generic modal helpers ──────────────────────────────────────
  function setupModalClose(modalEl) {
    if (!modalEl) return;
    var id = modalEl.id;
    modalEl.querySelectorAll('[data-modal-close="' + id + '"]').forEach(function(el) {
      el.addEventListener('click', function() { closeModal(modalEl); });
    });
  }
  function openModal(modalEl) {
    modalEl.hidden = false;
    void modalEl.offsetHeight;
    if (window.uiLockScroll) window.uiLockScroll();
  }
  function closeModal(modalEl) {
    if (modalEl.hidden) return;
    modalEl.hidden = true;
    if (window.uiUnlockScroll) window.uiUnlockScroll();
    var errEl = modalEl.querySelector('.movement-modal__error');
    if (errEl) errEl.hidden = true;
  }
  function showError(modalEl, msg) {
    var errEl = modalEl.querySelector('.movement-modal__error');
    if (errEl) { errEl.textContent = msg; errEl.hidden = false; }
  }

  // Global Escape key
  document.addEventListener('keydown', function(e) {
    if (e.key !== 'Escape') return;
    ['addMovementModal', 'addInvoiceModal', 'activityModal'].forEach(function(id) {
      var el = document.getElementById(id);
      if (el && !el.hidden) closeModal(el);
    });
  });

  // ── Tipo toggle helper ─────────────────────────────────────────
  function setupTipoToggle(container, hiddenInput) {
    if (!container) return;
    var btns = container.querySelectorAll('.mm-tipo-btn');
    btns.forEach(function(btn) {
      btn.addEventListener('click', function() {
        btns.forEach(function(b) { b.classList.remove('mm-tipo-btn--active'); });
        btn.classList.add('mm-tipo-btn--active');
        hiddenInput.value = btn.dataset.tipo;
      });
    });
  }

  // ══════════════════════════════════════════════════════════════
  // MODAL 1: Agregar Movimiento
  // ══════════════════════════════════════════════════════════════
  var movModal = document.getElementById('addMovementModal');
  if (movModal) {
    setupModalClose(movModal);
    var movForm = document.getElementById('addMovementForm');
    var movSubmit = document.getElementById('addMovementSubmit');
    var mmFechaHidden = document.getElementById('mmFechaHidden');
    var mmMonto = document.getElementById('mmMonto');
    var mmMoneda = document.getElementById('mmMoneda');
    var mmTipo = document.getElementById('mmTipo');
    var mmMoreToggle = document.getElementById('mmMoreToggle');
    var mmMoreSection = document.getElementById('mmMoreSection');

    setupTipoToggle(document.getElementById('mmTipoToggle'), mmTipo);

    // Default date
    if (mmFechaHidden) mmFechaHidden.value = today;

    // More details toggle
    if (mmMoreToggle && mmMoreSection) {
      mmMoreToggle.addEventListener('click', function() {
        var isHidden = mmMoreSection.hidden;
        mmMoreSection.hidden = !isHidden;
        mmMoreToggle.textContent = isHidden ? '－ Menos detalles' : '＋ Más detalles';
      });
    }

    // Open
    window.openAddMovementModal = function() {
      openModal(movModal);
      setTimeout(function() { if (mmMonto) mmMonto.focus(); }, 120);
    };

    // Submit
    if (movSubmit) movSubmit.addEventListener('click', function() {
      if (!movForm.checkValidity()) { movForm.reportValidity(); return; }
      var data = {
        tipo: mmTipo.value,
        fecha: mmFechaHidden.value || today,
        descripcion: document.getElementById('mmDesc').value,
        monto: parseFloat(document.getElementById('mmMonto').value),
        moneda: mmMoneda ? mmMoneda.value : 'MXN',
        forma_pago: document.getElementById('mmFormaPago').value || null,
        categoria: document.getElementById('mmCat').value || null,
        contraparte: document.getElementById('mmContraparte').value || null,
        notas: document.getElementById('mmNotas').value || null,
      };
      movSubmit.disabled = true; movSubmit.textContent = 'Guardando...';
      fetch('/api/movements/manual', {
        method: 'POST',
        headers: {'Content-Type': 'application/json', 'X-CSRF-Token': getCSRF()},
        body: JSON.stringify(data),
      })
      .then(function(r) { return r.json(); })
      .then(function(res) {
        if (res.ok) {
          if (window.portalToast) window.portalToast({type:'success', title:'Movimiento guardado'});
          movForm.reset();
          mmFechaHidden.value = today;
          if (mmMoneda) mmMoneda.value = 'MXN';
          // Reset tipo to GASTO
          var btns = movModal.querySelectorAll('.mm-tipo-btn');
          btns.forEach(function(b) { b.classList.remove('mm-tipo-btn--active'); });
          btns.forEach(function(b) { if (b.dataset.tipo === 'GASTO') b.classList.add('mm-tipo-btn--active'); });
          mmTipo.value = 'GASTO';
          // Collapse more
          if (mmMoreSection) mmMoreSection.hidden = true;
          if (mmMoreToggle) mmMoreToggle.textContent = '＋ Más detalles';
          closeModal(movModal);
          if (location.pathname.indexOf('/movimientos') !== -1) setTimeout(function() { location.reload(); }, 300);
        } else {
          showError(movModal, (res.error && res.error.message) || res.detail || 'Error al guardar');
        }
      })
      .catch(function() { showError(movModal, 'Error de conexión'); })
      .finally(function() { movSubmit.disabled = false; movSubmit.textContent = 'Guardar'; });
    });
  }

  // ══════════════════════════════════════════════════════════════
  // MODAL 2: Agregar Invoice
  // ══════════════════════════════════════════════════════════════
  var invModal = document.getElementById('addInvoiceModal');
  if (invModal) {
    setupModalClose(invModal);
    var invForm = document.getElementById('addInvoiceForm');
    var invSubmit = document.getElementById('addInvoiceSubmit');
    var fiTipo = document.getElementById('fiTipo');
    var fiFecha = document.getElementById('fiFecha');
    var fiMontoOrig = document.getElementById('fiMontoOrig');
    var fiTipoCambio = document.getElementById('fiTipoCambio');
    var fiEquivEl = document.getElementById('fiEquivMxn');

    setupTipoToggle(document.getElementById('fiTipoToggle'), fiTipo);

    if (fiFecha && !fiFecha.value) fiFecha.value = today;

    // MXN equivalent calc
    function updateEquiv() {
      var m = fiMontoOrig ? (parseFloat(fiMontoOrig.value) || 0) : 0;
      var tc = fiTipoCambio ? (parseFloat(fiTipoCambio.value) || 0) : 0;
      var total = m * tc;
      if (fiEquivEl) fiEquivEl.innerHTML = 'Equivalente: <strong>' + formatMoney(total) + ' MXN</strong>';
    }
    window._updateInvoiceEquiv = updateEquiv;
    if (fiMontoOrig) fiMontoOrig.addEventListener('input', updateEquiv);
    if (fiTipoCambio) fiTipoCambio.addEventListener('input', updateEquiv);

    // Auto-fetch exchange rate from DB when date or currency changes
    var fiMoneda = document.getElementById('fiMoneda');
    function fetchExchangeRate() {
      var fecha = fiFecha ? fiFecha.value : '';
      var moneda = fiMoneda ? fiMoneda.value : 'USD';
      if (!fecha || fecha.length < 7) return;
      var period = fecha.substring(0, 7);
      fetch('/api/exchange-rate?moneda=' + encodeURIComponent(moneda) + '&period=' + encodeURIComponent(period), {credentials: 'same-origin'})
        .then(function(r) { return r.json(); })
        .then(function(res) {
          if (res.ok && res.data && res.data.rate && fiTipoCambio) {
            fiTipoCambio.value = res.data.rate;
            updateEquiv();
          }
        })
        .catch(function() {});
    }
    if (fiFecha) fiFecha.addEventListener('change', fetchExchangeRate);
    if (fiMoneda) fiMoneda.addEventListener('change', fetchExchangeRate);

    // Open (with optional prefill from PDF extraction)
    window.openAddInvoiceModal = function(prefillData) {
      openModal(invModal);
      if (prefillData) {
        if (prefillData.fecha && fiFecha) fiFecha.value = prefillData.fecha;
        var fiNum = document.getElementById('fiNumber');
        if (prefillData.invoice_number && fiNum) fiNum.value = prefillData.invoice_number;
        var fiEmp = document.getElementById('fiEmpresa');
        if (prefillData.empresa && fiEmp) fiEmp.value = prefillData.empresa;
        if (prefillData.moneda && fiMoneda) {
          for (var i = 0; i < fiMoneda.options.length; i++) {
            if (fiMoneda.options[i].value === prefillData.moneda) { fiMoneda.selectedIndex = i; break; }
          }
        }
        if (prefillData.monto_original && fiMontoOrig) fiMontoOrig.value = prefillData.monto_original;
        var fiDescEl = document.getElementById('fiDesc');
        if (prefillData.descripcion && fiDescEl) fiDescEl.value = prefillData.descripcion;
        var fiTaxEl = document.getElementById('fiTaxId');
        if (prefillData.tax_id && fiTaxEl) fiTaxEl.value = prefillData.tax_id;
        if (prefillData.pais) {
          var paisSel = document.getElementById('fiPais');
          if (paisSel) for (var j = 0; j < paisSel.options.length; j++) {
            if (paisSel.options[j].value === prefillData.pais || paisSel.options[j].text === prefillData.pais) {
              paisSel.selectedIndex = j; break;
            }
          }
        }
        // Set tipo toggle from backend detection
        if (prefillData.tipo) {
          var tipoBtns = invModal.querySelectorAll('.mm-tipo-btn');
          tipoBtns.forEach(function(b) { b.classList.remove('mm-tipo-btn--active'); });
          tipoBtns.forEach(function(b) { if (b.dataset.tipo === prefillData.tipo) b.classList.add('mm-tipo-btn--active'); });
          fiTipo.value = prefillData.tipo;
        }
        // Auto-fetch exchange rate for the invoice month
        fetchExchangeRate();
        updateEquiv();
      }
      var focusEl = document.getElementById('fiNumber');
      setTimeout(function() { if (focusEl) focusEl.focus(); }, 120);
    };

    // Mini upload zone in modal
    var modalUpload = document.getElementById('invoiceModalUpload');
    var modalFileInput = document.getElementById('invoiceModalFileInput');
    var modalBrowse = document.getElementById('invoiceModalBrowse');
    if (modalUpload && modalFileInput) {
      if (modalBrowse) modalBrowse.addEventListener('click', function() { modalFileInput.click(); });
      modalUpload.addEventListener('dragover', function(e) { e.preventDefault(); modalUpload.classList.add('is-dragover'); });
      modalUpload.addEventListener('dragleave', function() { modalUpload.classList.remove('is-dragover'); });
      modalUpload.addEventListener('drop', function(e) {
        e.preventDefault(); modalUpload.classList.remove('is-dragover');
        if (e.dataTransfer.files.length) extractInvoicePDF(e.dataTransfer.files[0], modalUpload.querySelector('.invoice-modal-upload__inner'));
      });
      modalFileInput.addEventListener('change', function() {
        if (modalFileInput.files.length) extractInvoicePDF(modalFileInput.files[0], modalUpload.querySelector('.invoice-modal-upload__inner'));
        modalFileInput.value = '';
      });
    }

    // Submit
    if (invSubmit) invSubmit.addEventListener('click', function() {
      if (!invForm.checkValidity()) { invForm.reportValidity(); return; }
      var data = {
        tipo: fiTipo.value,
        fecha: fiFecha.value,
        invoice_number: document.getElementById('fiNumber').value,
        empresa: document.getElementById('fiEmpresa').value,
        pais: document.getElementById('fiPais').value || null,
        tax_id: document.getElementById('fiTaxId').value || null,
        descripcion: document.getElementById('fiDesc').value,
        moneda: document.getElementById('fiMoneda').value,
        monto_original: parseFloat(fiMontoOrig.value),
        tipo_cambio: parseFloat(fiTipoCambio.value),
        forma_pago: document.getElementById('fiFormaPago').value || null,
        referencia_pago: document.getElementById('fiRefPago').value || null,
        notas: document.getElementById('fiNotas').value || null,
      };
      invSubmit.disabled = true; invSubmit.textContent = 'Guardando...';
      fetch('/api/movements/invoice', {
        method: 'POST',
        headers: {'Content-Type': 'application/json', 'X-CSRF-Token': getCSRF()},
        body: JSON.stringify(data),
      })
      .then(function(r) { return r.json(); })
      .then(function(res) {
        if (res.ok) {
          if (window.portalToast) window.portalToast({type:'success', title:'Invoice guardado'});
          invForm.reset();
          fiFecha.value = today;
          var btns = invModal.querySelectorAll('.mm-tipo-btn');
          btns.forEach(function(b) { b.classList.remove('mm-tipo-btn--active'); });
          btns.forEach(function(b) { if (b.dataset.tipo === 'INGRESO') b.classList.add('mm-tipo-btn--active'); });
          fiTipo.value = 'INGRESO';
          updateEquiv();
          closeModal(invModal);
          if (location.pathname.indexOf('/invoices-ext') !== -1) setTimeout(function() { location.reload(); }, 300);
        } else {
          showError(invModal, (res.error && res.error.message) || res.detail || 'Error al guardar');
        }
      })
      .catch(function() { showError(invModal, 'Error de conexión'); })
      .finally(function() { invSubmit.disabled = false; invSubmit.textContent = 'Guardar Invoice'; });
    });
  }

  // ── PDF extraction helper ──────────────────────────────────────
  // Sequential batch: process one file at a time to avoid concurrency issues
  var _batchQueue = [];
  var _batchRunning = false;
  var _savedCount = 0;
  var _failedCount = 0;
  var _dupCount = 0;
  var _batchOrigHTML = '';
  var _batchInnerEl = null;
  var _batchTotal = 0;

  function _batchFinish() {
    if (_batchInnerEl) _batchInnerEl.innerHTML = _batchOrigHTML;
    var parts = [];
    if (_savedCount > 0) parts.push(_savedCount === 1 ? '1 invoice guardado' : _savedCount + ' invoices guardados');
    if (_dupCount > 0) parts.push(_dupCount === 1 ? '1 duplicado omitido' : _dupCount + ' duplicados omitidos');
    if (_failedCount > 0) parts.push(_failedCount === 1 ? '1 falló' : _failedCount + ' fallaron');
    if (_savedCount > 0) {
      if (window.portalToast) window.portalToast({type: 'success', title: parts.join(' · ')});
      setTimeout(function() { location.reload(); }, 800);
    } else if (_dupCount > 0 && _failedCount === 0) {
      if (window.portalToast) window.portalToast({type: 'info', title: parts.join(' · ')});
    } else if (_failedCount > 0) {
      if (window.portalToast) window.portalToast({type: 'warning', title: parts.join(' · ')});
    }
    _savedCount = 0; _failedCount = 0; _dupCount = 0; _batchTotal = 0;
    _batchRunning = false;
  }

  function _processNext() {
    if (_batchQueue.length === 0) { _batchFinish(); return; }
    var item = _batchQueue.shift();
    var file = item.file, innerEl = item.innerEl, autoSave = item.autoSave;
    var idx = _batchTotal - _batchQueue.length;
    if (innerEl) innerEl.innerHTML = '<div style="display:flex;align-items:center;gap:8px;justify-content:center;padding:8px;color:var(--text-muted);font-size:13px;"><span class="btn__spinner"></span> Procesando ' + idx + '/' + _batchTotal + ': ' + file.name + '</div>';
    var fd = new FormData();
    fd.append('file', file);
    var url = '/api/invoices/extract-pdf' + (autoSave ? '?auto_save=true' : '');
    fetch(url, {
      method: 'POST',
      body: fd,
      credentials: 'same-origin',
      headers: {'X-CSRF-Token': getCSRF()},
    })
    .then(function(r) { return r.json(); })
    .then(function(res) {
      if (!res.ok || !res.data) {
        _failedCount++;
        if (window.portalToast) window.portalToast({type:'error', title:'Error: ' + file.name, message: res.error || res.detail || 'No se pudo procesar'});
        _processNext();
        return;
      }
      var d = res.data;
      if (autoSave && d.auto_saved) {
        _savedCount++;
        _processNext();
        return;
      }
      if (autoSave && d.duplicate) {
        _dupCount++;
        _processNext();
        return;
      }
      if (autoSave && !d.auto_saved) {
        _failedCount++;
        window.openAddInvoiceModal(d);
        var warnMsg = d.reason === 'no_amount' ? 'No se pudo detectar el monto.' : d.tipo_undetected ? 'Confirma si es ingreso o gasto.' : 'Revisa los datos extraídos';
        if (window.portalToast) window.portalToast({type:'warning', title:'Completa los datos de ' + file.name, message: warnMsg});
        _processNext();
        return;
      }
      // Manual mode: open modal with prefill
      if (innerEl) innerEl.innerHTML = _batchOrigHTML;
      if (invModal && !invModal.hidden) {
        prefillInvoiceForm(d);
      } else {
        window.openAddInvoiceModal(d);
      }
      if (window.portalToast) window.portalToast({type:'info', title:'Datos extraídos del PDF', message:'Revisa que estén correctos'});
      _processNext();
    })
    .catch(function(err) {
      _failedCount++;
      if (window.portalToast) window.portalToast({type:'error', title:'Error al procesar ' + file.name, message: err.message || ''});
      _processNext();
    });
  }

  var _batchStartTimer = null;
  function extractInvoicePDF(file, innerEl, autoSave) {
    if (!file.name.toLowerCase().endsWith('.pdf')) {
      if (window.portalToast) window.portalToast({type:'error', title:'Solo se aceptan archivos PDF'});
      return;
    }
    if (!_batchRunning) {
      _batchRunning = true;
      _savedCount = 0; _failedCount = 0; _dupCount = 0; _batchTotal = 0;
      if (innerEl) _batchOrigHTML = innerEl.innerHTML;
      _batchInnerEl = innerEl;
    }
    _batchQueue.push({file: file, innerEl: innerEl, autoSave: !!autoSave});
    _batchTotal++;
    // Debounce: start processing after all files from the loop are queued
    clearTimeout(_batchStartTimer);
    _batchStartTimer = setTimeout(function() { _processNext(); }, 50);
  }
  window.extractInvoicePDF = extractInvoicePDF;

  function prefillInvoiceForm(data) {
    var el;
    if (data.fecha && (el = document.getElementById('fiFecha'))) el.value = data.fecha;
    if (data.invoice_number && (el = document.getElementById('fiNumber'))) el.value = data.invoice_number;
    if (data.empresa && (el = document.getElementById('fiEmpresa'))) el.value = data.empresa;
    if (data.descripcion && (el = document.getElementById('fiDesc'))) el.value = data.descripcion;
    if (data.tax_id && (el = document.getElementById('fiTaxId'))) el.value = data.tax_id;
    if (data.monto_original && (el = document.getElementById('fiMontoOrig'))) el.value = data.monto_original;
    if (data.moneda && (el = document.getElementById('fiMoneda'))) {
      for (var i = 0; i < el.options.length; i++) {
        if (el.options[i].value === data.moneda) { el.selectedIndex = i; break; }
      }
    }
    if (data.pais && (el = document.getElementById('fiPais'))) {
      for (var j = 0; j < el.options.length; j++) {
        if (el.options[j].value === data.pais || el.options[j].text === data.pais) { el.selectedIndex = j; break; }
      }
    }
    // Set tipo toggle from backend detection
    if (data.tipo) {
      var tipoBtns = document.querySelectorAll('#fiTipoToggle .mm-tipo-btn');
      tipoBtns.forEach(function(b) { b.classList.remove('mm-tipo-btn--active'); });
      tipoBtns.forEach(function(b) { if (b.dataset.tipo === data.tipo) b.classList.add('mm-tipo-btn--active'); });
      var fiTipoEl = document.getElementById('fiTipo');
      if (fiTipoEl) fiTipoEl.value = data.tipo;
    }
    if (window._updateInvoiceEquiv) window._updateInvoiceEquiv();
  }

  // ══════════════════════════════════════════════════════════════
  // MODAL 3: Actividad Reciente
  // ══════════════════════════════════════════════════════════════
  var actModal = document.getElementById('activityModal');
  if (actModal) {
    setupModalClose(actModal);
    var actList = document.getElementById('activityModalList');
    var actFilterTabs = actModal.querySelectorAll('.movement-modal__tabs .movement-modal__tab');
    var actAllItems = [];

    window.openActivityModal = function() {
      openModal(actModal);
      loadActivity();
    };

    actFilterTabs.forEach(function(t) {
      t.addEventListener('click', function() {
        actFilterTabs.forEach(function(x) { x.classList.remove('movement-modal__tab--active'); });
        t.classList.add('movement-modal__tab--active');
        renderActivity(t.dataset.filter);
      });
    });

    function loadActivity() {
      actList.innerHTML = '<li class="activity-modal__loading">Cargando...</li>';
      fetch('/api/activity?limit=100', {credentials:'same-origin'})
        .then(function(r) { return r.json(); })
        .then(function(res) {
          actAllItems = res.items || (res.data && res.data.items) || [];
          actFilterTabs.forEach(function(t) { t.classList.toggle('movement-modal__tab--active', t.dataset.filter === 'all'); });
          renderActivity('all');
        })
        .catch(function() { actList.innerHTML = '<li class="activity-modal__loading">Error al cargar</li>'; });
    }

    function renderActivity(filter) {
      var items = actAllItems;
      if (filter === 'received') items = items.filter(function(a) { return a.direction === 'received'; });
      if (filter === 'issued') items = items.filter(function(a) { return a.direction === 'issued'; });
      if (!items.length) { actList.innerHTML = '<li class="activity-modal__empty">Sin actividad reciente</li>'; return; }
      actList.innerHTML = items.map(function(a) {
        var isIssued = a.direction === 'issued';
        var label = isIssued ? 'Emitida' : 'Recibida';
        var name = a.nombre || 'Sin nombre';
        var url = '/portal/cfdi/' + (isIssued ? 'issued' : 'received') + '/' + (a.uuid || '');
        return '<li><a href="' + url + '" class="activity-modal__item">' +
          '<span class="activity-modal__icon activity-modal__icon--' + a.direction + '">' + (isIssued ? '&#8593;' : '&#8595;') + '</span>' +
          '<div class="activity-modal__content"><div class="activity-modal__top">' +
          '<span class="activity-modal__badge activity-modal__badge--' + a.direction + '">' + label + '</span>' +
          '<span class="activity-modal__name">' + (name.length > 40 ? name.substring(0,40) + '...' : name) + '</span></div>' +
          '<div class="activity-modal__meta"><span class="activity-modal__time">' + (a.time_ago || '') + '</span></div></div>' +
          (a.total ? '<span class="activity-modal__amount">' + formatMoney(a.total) + '</span>' : '') +
          '</a></li>';
      }).join('');
    }
  }

  // Keep legacy alias for backward compat
  window.openMovementModal = function(tab) {
    if (tab === 'foreign') { window.openAddInvoiceModal(); }
    else { window.openAddMovementModal(); }
  };

})();
