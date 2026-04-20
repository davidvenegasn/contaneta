/* Guides page — search, chip filters, accordion toggle */
(function () {
  'use strict';

  var search = document.getElementById('guidesSearch');
  var chipsWrap = document.getElementById('guidesChips');
  var noResults = document.getElementById('guidesNoResults');
  if (!search || !chipsWrap) return;

  var items = Array.from(document.querySelectorAll('.guide-item'));
  var chips = Array.from(chipsWrap.querySelectorAll('.guides-chip'));
  var sections = Array.from(document.querySelectorAll('.guides-section'));

  /* ---- Helpers ---- */
  function normalize(s) {
    return (s || '').toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '');
  }

  function activeTag() {
    var active = chipsWrap.querySelector('.guides-chip.is-active');
    return active ? active.getAttribute('data-tag') : 'todos';
  }

  function applyFilters() {
    var q = normalize(search.value.trim());
    var tag = activeTag();
    var visible = 0;

    items.forEach(function (el) {
      var tags = normalize(el.getAttribute('data-tags') || '');
      var text = normalize(el.textContent);
      var matchTag = tag === 'todos' || tags.indexOf(normalize(tag)) !== -1;
      var matchSearch = !q || text.indexOf(q) !== -1 || tags.indexOf(q) !== -1;
      var show = matchTag && matchSearch;
      el.style.display = show ? '' : 'none';
      if (show) visible++;
    });

    // Hide sections whose items are all hidden
    sections.forEach(function (sec) {
      var any = Array.from(sec.querySelectorAll('.guide-item')).some(function (i) {
        return i.style.display !== 'none';
      });
      sec.style.display = any ? '' : 'none';
    });

    if (noResults) noResults.hidden = visible > 0;
  }

  /* ---- Search ---- */
  search.addEventListener('input', applyFilters);

  /* ---- Chip filters ---- */
  chips.forEach(function (chip) {
    chip.addEventListener('click', function () {
      chips.forEach(function (c) { c.classList.remove('is-active'); });
      chip.classList.add('is-active');
      applyFilters();
    });
  });

  /* ---- Accordion toggle ---- */
  document.addEventListener('click', function (e) {
    var toggle = e.target.closest('.guide-accordion__toggle');
    if (!toggle) return;
    var body = toggle.nextElementSibling;
    if (!body || !body.classList.contains('guide-accordion__body')) return;
    var expanded = toggle.getAttribute('aria-expanded') === 'true';
    toggle.setAttribute('aria-expanded', String(!expanded));
    body.hidden = expanded;
  });

})();
