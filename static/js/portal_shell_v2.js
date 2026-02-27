/**
 * Portal Shell V2 — Rail + Drawer (Mindtrip-style)
 * - Toggle drawer, persist state en localStorage, ESC y backdrop para cerrar.
 * - Toggle rail expandir/comprimir, persistir en localStorage.
 * - Trigger usuario en rail: abrir mismo dropdown de cuenta (posición desde rail).
 */
(function () {
  var STORAGE_KEY_DRAWER = 'portal_drawer_open';
  var STORAGE_KEY_RAIL = 'portal_rail_expanded';
  var shell = document.querySelector('[data-portal-shell]');
  if (!shell || !shell.classList.contains('portal-shell--v2')) return;

  var rail = document.getElementById('portalRail');
  var railExpandBtn = document.getElementById('portalRailExpand');
  var userMenuBtnRail = document.getElementById('userMenuBtnRail');
  var openBtn = document.getElementById('portalDrawerOpen');
  var openBtnTopbar = document.getElementById('portalDrawerOpenTopbar');
  var closeBtn = document.getElementById('portalDrawerClose');
  var drawer = document.getElementById('portalDrawer');
  var backdrop = document.getElementById('portalDrawerBackdrop');

  // ---------- Drawer ----------
  function isDrawerOpen() {
    return drawer && drawer.getAttribute('aria-hidden') === 'false';
  }

  function openDrawer() {
    if (!drawer || !backdrop) return;
    drawer.removeAttribute('hidden');
    drawer.setAttribute('aria-hidden', 'false');
    backdrop.removeAttribute('hidden');
    backdrop.setAttribute('aria-hidden', 'false');
    shell.classList.add('portal-shell--drawer-open');
    try { localStorage.setItem(STORAGE_KEY_DRAWER, '1'); } catch (e) {}
    if (closeBtn) closeBtn.focus();
  }

  function closeDrawer() {
    if (!drawer || !backdrop) return;
    drawer.setAttribute('aria-hidden', 'true');
    drawer.setAttribute('hidden', '');
    backdrop.setAttribute('aria-hidden', 'true');
    backdrop.setAttribute('hidden', '');
    shell.classList.remove('portal-shell--drawer-open');
    try { localStorage.setItem(STORAGE_KEY_DRAWER, '0'); } catch (e) {}
    if (openBtn) openBtn.focus();
  }

  if (openBtn) openBtn.addEventListener('click', function () { if (isDrawerOpen()) closeDrawer(); else openDrawer(); });
  if (openBtnTopbar) openBtnTopbar.addEventListener('click', openDrawer);
  if (closeBtn) closeBtn.addEventListener('click', closeDrawer);
  if (backdrop) backdrop.addEventListener('click', closeDrawer);

  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && isDrawerOpen()) closeDrawer();
  });

  try {
    if (localStorage.getItem(STORAGE_KEY_DRAWER) === '1') openDrawer();
  } catch (e) {}

  // ---------- Rail expandir / comprimir ----------
  function isRailExpanded() {
    return rail && rail.getAttribute('data-expanded') === 'true';
  }

  function setRailExpanded(expanded) {
    if (!rail) return;
    rail.setAttribute('data-expanded', expanded ? 'true' : 'false');
    if (railExpandBtn) {
      railExpandBtn.setAttribute('aria-expanded', expanded ? 'true' : 'false');
      railExpandBtn.setAttribute('aria-label', expanded ? 'Comprimir menú' : 'Expandir menú');
      railExpandBtn.setAttribute('title', expanded ? 'Comprimir menú' : 'Expandir menú');
    }
    if (expanded) {
      shell.classList.add('portal-shell--rail-expanded');
      rail.classList.add('portal-rail--expanded');
    } else {
      shell.classList.remove('portal-shell--rail-expanded');
      rail.classList.remove('portal-rail--expanded');
    }
    try { localStorage.setItem(STORAGE_KEY_RAIL, expanded ? '1' : '0'); } catch (e) {}
  }

  function toggleRail() {
    setRailExpanded(!isRailExpanded());
  }

  if (railExpandBtn) {
    railExpandBtn.addEventListener('click', toggleRail);
  }

  // Rail siempre empieza delgado (solo iconos), como Mindtrip. Opcional: restaurar expandido con localStorage.
  // try { if (localStorage.getItem(STORAGE_KEY_RAIL) === '1') setRailExpanded(true); } catch (e) {}

  // ---------- Usuario en rail: abrir dropdown de cuenta ----------
  if (userMenuBtnRail) {
    userMenuBtnRail.addEventListener('click', function (e) {
      e.stopPropagation();
      var userMenu = document.getElementById('userMenu');
      var userBtnTopbar = document.getElementById('userMenuBtn');
      if (!userMenu) return;
      var isOpen = !userMenu.hidden;
      if (isOpen) {
        userMenu.hidden = true;
        userMenuBtnRail.setAttribute('aria-expanded', 'false');
        if (userBtnTopbar) userBtnTopbar.setAttribute('aria-expanded', 'false');
        userMenu.classList.remove('user-menu--from-rail');
        return;
      }
      userMenu.classList.add('user-menu--from-rail');
      userMenu.removeAttribute('hidden');
      userMenu.hidden = false;
      userMenuBtnRail.setAttribute('aria-expanded', 'true');
      if (userBtnTopbar) userBtnTopbar.setAttribute('aria-expanded', 'true');
      if (typeof window.loadAccountChecklist === 'function') window.loadAccountChecklist();
      var rect = userMenuBtnRail.getBoundingClientRect();
      userMenu.style.left = (rect.right + 8) + 'px';
      userMenu.style.bottom = (window.innerHeight - rect.top + 8) + 'px';
      userMenu.style.top = 'auto';
      userMenu.style.right = 'auto';
    });
  }
})();
