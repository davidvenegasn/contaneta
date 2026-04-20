/**
 * Keyboard shortcuts — chord navigation (G → key) + single keys.
 * Loaded on all portal pages via base_portal.html.
 *
 * Shortcuts:
 *   G then H  → /portal/home
 *   G then M  → /portal/movimientos
 *   G then F  → /portal/facturas
 *   G then C  → /portal/catalogos
 *   G then Q  → /portal/cotizaciones
 *   G then S  → /portal/config/sat
 *   N         → /portal/create  (nueva factura)
 *   ?         → toggle help panel
 *   Cmd/Ctrl+K → command palette (handled in command-palette.js)
 *   Escape    → close help panel
 */
(function () {
  'use strict';

  var CHORD_TIMEOUT = 800; // ms to wait for second key after G
  var pendingChord = false;
  var chordTimer = null;
  var helpOpen = false;
  var helpEl = null;

  var chords = {
    h: '/portal/home',
    m: '/portal/movimientos',
    f: '/portal/facturas',
    c: '/portal/catalogos',
    q: '/portal/cotizaciones',
    s: '/portal/config/sat'
  };

  function isInputFocused() {
    var el = document.activeElement;
    if (!el) return false;
    var tag = el.tagName;
    if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return true;
    if (el.isContentEditable) return true;
    return false;
  }

  function navigate(url) {
    window.location.href = url;
  }

  function buildHelp() {
    if (helpEl) return;
    helpEl = document.createElement('div');
    helpEl.className = 'kb-help-overlay';
    helpEl.setAttribute('role', 'dialog');
    helpEl.setAttribute('aria-modal', 'true');
    helpEl.setAttribute('aria-label', 'Atajos de teclado');
    helpEl.innerHTML =
      '<div class="kb-help-backdrop"></div>' +
      '<div class="kb-help-panel">' +
        '<div class="kb-help-header">' +
          '<h2 class="kb-help-title">Atajos de teclado</h2>' +
          '<button class="kb-help-close" aria-label="Cerrar">&times;</button>' +
        '</div>' +
        '<div class="kb-help-body">' +
          '<div class="kb-help-section">' +
            '<h3 class="kb-help-section-title">Navegación (G luego…)</h3>' +
            '<div class="kb-help-row"><kbd>G</kbd> <kbd>H</kbd><span>Inicio</span></div>' +
            '<div class="kb-help-row"><kbd>G</kbd> <kbd>F</kbd><span>Facturas</span></div>' +
            '<div class="kb-help-row"><kbd>G</kbd> <kbd>M</kbd><span>Movimientos</span></div>' +
            '<div class="kb-help-row"><kbd>G</kbd> <kbd>C</kbd><span>Catálogos</span></div>' +
            '<div class="kb-help-row"><kbd>G</kbd> <kbd>Q</kbd><span>Cotizaciones</span></div>' +
            '<div class="kb-help-row"><kbd>G</kbd> <kbd>S</kbd><span>Config SAT</span></div>' +
          '</div>' +
          '<div class="kb-help-section">' +
            '<h3 class="kb-help-section-title">Acciones</h3>' +
            '<div class="kb-help-row"><kbd>N</kbd><span>Nueva factura</span></div>' +
            '<div class="kb-help-row"><kbd>⌘</kbd> <kbd>K</kbd><span>Búsqueda global</span></div>' +
            '<div class="kb-help-row"><kbd>?</kbd><span>Mostrar atajos</span></div>' +
            '<div class="kb-help-row"><kbd>Esc</kbd><span>Cerrar</span></div>' +
          '</div>' +
        '</div>' +
      '</div>';

    document.body.appendChild(helpEl);

    helpEl.querySelector('.kb-help-backdrop').addEventListener('click', closeHelp);
    helpEl.querySelector('.kb-help-close').addEventListener('click', closeHelp);
  }

  function openHelp() {
    buildHelp();
    helpEl.classList.add('is-open');
    helpOpen = true;
    document.body.classList.add('no-scroll');
  }

  function closeHelp() {
    if (!helpEl) return;
    helpEl.classList.remove('is-open');
    helpOpen = false;
    document.body.classList.remove('no-scroll');
  }

  function cancelChord() {
    pendingChord = false;
    clearTimeout(chordTimer);
  }

  document.addEventListener('keydown', function (e) {
    // Don't handle shortcuts when typing in inputs
    if (isInputFocused()) return;

    // Don't handle when command palette or other modal is open
    if (document.querySelector('.cmd-palette.is-open')) return;

    var key = e.key.toLowerCase();

    // Close help on Escape
    if (key === 'escape' && helpOpen) {
      e.preventDefault();
      closeHelp();
      return;
    }

    // Ignore if any modifier (except Shift for ?)
    if (e.metaKey || e.ctrlKey || e.altKey) return;

    // Help toggle
    if (key === '?' || (e.shiftKey && key === '/')) {
      e.preventDefault();
      cancelChord();
      if (helpOpen) closeHelp();
      else openHelp();
      return;
    }

    // If help panel is open, only Escape closes it (handled above)
    if (helpOpen) return;

    // Chord: second key after G
    if (pendingChord) {
      cancelChord();
      if (chords[key]) {
        e.preventDefault();
        navigate(chords[key]);
      }
      return;
    }

    // Chord start: G
    if (key === 'g' && !e.shiftKey) {
      pendingChord = true;
      chordTimer = setTimeout(cancelChord, CHORD_TIMEOUT);
      return;
    }

    // Single-key shortcuts
    if (key === 'n' && !e.shiftKey) {
      e.preventDefault();
      navigate('/portal/create');
      return;
    }
  });
})();
