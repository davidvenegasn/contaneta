/* portal_dashboard_v2.js
   - Aplica/quita clase .pv2-dark en <body>.
   - Botón flotante abajo-derecha para toggle.
   - Persiste en localStorage.
   - Añade la clase .pv2 al <body> si no la tiene (activa el theming v2).
*/
(function () {
  const STORAGE_KEY = 'contaneta:dashboard:theme';

  function ensureBodyClass() {
    if (!document.body) return;
    document.body.classList.add('pv2');
  }

  function applyStoredTheme() {
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      if (saved === 'dark') document.body.classList.add('pv2-dark');
      else document.body.classList.remove('pv2-dark');
    } catch (e) {}
  }

  function createToggleButton() {
    if (document.querySelector('.pv2-theme-toggle')) return;
    const btn = document.createElement('button');
    btn.className = 'pv2-theme-toggle';
    btn.type = 'button';
    btn.title = 'Cambiar tema (claro / oscuro)';
    btn.setAttribute('aria-label', 'Cambiar tema');
    btn.innerHTML = `
      <svg class="pv2-moon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>
      <svg class="pv2-sun" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41"/></svg>
    `;
    btn.addEventListener('click', () => {
      const isDark = document.body.classList.toggle('pv2-dark');
      try { localStorage.setItem(STORAGE_KEY, isDark ? 'dark' : 'light'); } catch (e) {}
    });
    document.body.appendChild(btn);
  }

  function init() {
    ensureBodyClass();
    applyStoredTheme();
    createToggleButton();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
