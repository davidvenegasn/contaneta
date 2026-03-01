(function () {
  var shell = document.querySelector('[data-portal-shell]');
  if (!shell) return;

  var toggleBtn = shell.querySelector('[data-drawer-toggle]');
  var KEY = 'portal_drawer_open';
  var MOBILE_BP = 1100;

  function isMobile() {
    return window.innerWidth < MOBILE_BP;
  }

  /* ---------- Desktop drawer (rail expand) ---------- */
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
  if (init && !isMobile()) {
    shell.classList.add('drawer-instant');
    setOpen(true);
    requestAnimationFrame(function () {
      requestAnimationFrame(function () {
        shell.classList.remove('drawer-instant');
      });
    });
  } else if (!isMobile()) {
    setOpen(false);
  }

  if (toggleBtn) {
    toggleBtn.addEventListener('click', function (e) {
      e.preventDefault();
      setOpen(!shell.classList.contains('drawer-open'));
    });
  }

  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') {
      if (isMobile() && document.body.classList.contains('mobile-menu-open')) {
        closeMobileMenu();
      } else {
        setOpen(false);
      }
    }
  });

  /* ---------- Mobile menu (hamburger → overlay) ---------- */
  var mobileMenuBtn = document.getElementById('mobileMenuBtn');
  var mobileMenuClose = document.getElementById('mobileMenuClose');

  function openMobileMenu() {
    document.body.classList.add('mobile-menu-open');
    if (mobileMenuBtn) mobileMenuBtn.setAttribute('aria-expanded', 'true');
  }

  function closeMobileMenu() {
    document.body.classList.remove('mobile-menu-open');
    if (mobileMenuBtn) mobileMenuBtn.setAttribute('aria-expanded', 'false');
  }

  if (mobileMenuBtn) {
    mobileMenuBtn.addEventListener('click', function () {
      if (document.body.classList.contains('mobile-menu-open')) {
        closeMobileMenu();
      } else {
        openMobileMenu();
      }
    });
  }

  if (mobileMenuClose) {
    mobileMenuClose.addEventListener('click', function () {
      closeMobileMenu();
    });
  }

  /* Close mobile menu on backdrop click */
  document.addEventListener('click', function (e) {
    if (!document.body.classList.contains('mobile-menu-open')) return;
    var sidebar = document.querySelector('.portal-sidebar-unified');
    if (sidebar && !sidebar.contains(e.target) && e.target !== mobileMenuBtn) {
      closeMobileMenu();
    }
  });

  /* Close mobile menu on resize to desktop */
  window.addEventListener('resize', function () {
    if (!isMobile() && document.body.classList.contains('mobile-menu-open')) {
      closeMobileMenu();
    }
  });

  window.openMobileMenu = openMobileMenu;
  window.closeMobileMenu = closeMobileMenu;
})();
