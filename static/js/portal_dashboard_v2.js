/* portal_dashboard_v2.js
   - Syncs .pv2-dark on <body> with the portal's html.nightmode toggle.
   - Adds the .pv2 class to <body> (activates v2 theming tokens).
   - Listens for nightmode changes and keeps pv2-dark in sync.
*/
(function () {
  var PORTAL_KEY = 'portal_nightmode';

  function ensureBodyClass() {
    if (!document.body) return;
    document.body.classList.add('pv2');
  }

  function syncWithPortalNightmode() {
    var isNight = document.documentElement.classList.contains('nightmode');
    document.body.classList.toggle('pv2-dark', isNight);
  }

  function init() {
    ensureBodyClass();
    syncWithPortalNightmode();

    // Watch for nightmode class changes on <html> to stay in sync
    var observer = new MutationObserver(function () {
      syncWithPortalNightmode();
    });
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ['class']
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
