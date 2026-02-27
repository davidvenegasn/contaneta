(function () {
  const shell = document.querySelector('[data-portal-shell]');
  if (!shell) return;

  const toggleBtn = shell.querySelector('[data-drawer-toggle]');
  const KEY = 'portal_drawer_open';

  function updateToggleLabel(open) {
    if (!toggleBtn) return;
    var tooltip = toggleBtn.querySelector('.rail-tooltip');
    if (open) {
      toggleBtn.setAttribute('aria-label', 'Cerrar menú');
      toggleBtn.setAttribute('title', 'Cerrar menú');
      if (tooltip) tooltip.textContent = 'Cerrar menú';
    } else {
      toggleBtn.setAttribute('aria-label', 'Expandir menú');
      toggleBtn.setAttribute('title', 'Expandir');
      if (tooltip) tooltip.textContent = 'Expandir';
    }
  }

  function setOpen(v) {
    shell.classList.toggle('drawer-open', v);
    updateToggleLabel(v);
    try {
      localStorage.setItem(KEY, v ? '1' : '0');
    } catch (e) {}
  }

  var init = false;
  try {
    init = localStorage.getItem(KEY) === '1';
  } catch (e) {}
  if (init) {
    shell.classList.add('drawer-instant');
    setOpen(true);
    requestAnimationFrame(function () {
      requestAnimationFrame(function () {
        shell.classList.remove('drawer-instant');
      });
    });
  } else {
    setOpen(false);
  }

  toggleBtn?.addEventListener('click', function (e) {
    e.preventDefault();
    setOpen(!shell.classList.contains('drawer-open'));
  });

  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') setOpen(false);
  });
})();
