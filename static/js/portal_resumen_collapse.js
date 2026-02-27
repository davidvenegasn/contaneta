/**
 * Resumen colapsable: botón de ojo para ocultar/mostrar totales (proteger privacidad en screenshots).
 * Estado persistido en localStorage para todas las páginas y entre sesiones.
 */
(function () {
  var KEY = 'portal_resumen_collapsed';
  var EYE_OPEN = '<svg class="icon ym-card__toggle-svg" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/><circle cx="12" cy="12" r="3" stroke="currentColor" stroke-width="2"/></svg>';
  var EYE_OFF = '<svg class="icon ym-card__toggle-svg" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M17.94 17.94A10.94 10.94 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/><line x1="1" y1="1" x2="23" y2="23" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>';

  function initCard(card) {
    var resumen = card.querySelector('.ym-card__resumen');
    var btn = card.querySelector('.ym-card__toggle');
    if (!resumen || !btn) return;

    function isCollapsed() {
      try { return localStorage.getItem(KEY) === '1'; } catch (e) { return false; }
    }

    function setCollapsed(collapsed) {
      try { localStorage.setItem(KEY, collapsed ? '1' : '0'); } catch (e) {}
      card.classList.toggle('ym-card--collapsed', collapsed);
      resumen.hidden = collapsed;
      resumen.setAttribute('aria-hidden', collapsed ? 'true' : 'false');

      var iconWrap = btn.querySelector('.ym-card__toggle-icon');
      var label = btn.querySelector('.ym-card__toggle-label');
      if (iconWrap) iconWrap.innerHTML = collapsed ? EYE_OFF : EYE_OPEN;
      if (label) label.textContent = collapsed ? 'Mostrar totales' : 'Ocultar totales';
      btn.setAttribute('aria-label', collapsed ? 'Mostrar totales' : 'Ocultar totales');
      btn.setAttribute('title', collapsed ? 'Mostrar totales (para ver ingresos/egresos)' : 'Ocultar totales (proteger tu información)');
    }

    setCollapsed(isCollapsed());
    btn.addEventListener('click', function (e) {
      e.preventDefault();
      setCollapsed(!isCollapsed());
    });
  }

  function run() {
    document.querySelectorAll('.ym-card--collapsible').forEach(initCard);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', run);
  } else {
    run();
  }
})();
