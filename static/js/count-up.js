/**
 * Count-up animado (estilo fintech/Revolut). Sin dependencias.
 * Respeta prefers-reduced-motion: muestra valor final de inmediato.
 *
 * Uso: elemento con data-count-to="1234.5" (y opcionalmente data-count-from, data-count-duration,
 * data-count-prefix, data-count-suffix, data-count-decimals, data-count-view="once").
 */
(function () {
  'use strict';

  function prefersReducedMotion() {
    return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  }

  function formatNumber(value, decimals, prefix, suffix) {
    var n = Number(value);
    if (isNaN(n)) return '';
    var s = decimals != null && decimals >= 0
      ? n.toFixed(decimals)
      : n % 1 === 0 ? String(Math.round(n)) : n.toFixed(2);
    if (typeof Intl !== 'undefined' && Intl.NumberFormat && (decimals == null || decimals === 0)) {
      try {
        s = new Intl.NumberFormat(undefined, {
          maximumFractionDigits: decimals != null ? decimals : 2,
          minimumFractionDigits: decimals != null ? decimals : 0
        }).format(n);
      } catch (e) {}
    }
    return (prefix || '') + s + (suffix || '');
  }

  /**
   * Ease out expo: sensación premium, rápido al inicio y suave al final.
   */
  function easeOutExpo(t) {
    return t === 1 ? 1 : 1 - Math.pow(2, -10 * t);
  }

  function countUp(el, opts) {
    if (!el || !el.nodeType) return;
    if (el._countUpDone) return;
    el._countUpDone = true;
    var to = parseFloat(el.getAttribute('data-count-to'));
    if (isNaN(to)) return;
    var from = parseFloat(el.getAttribute('data-count-from')) || 0;
    var duration = parseInt(el.getAttribute('data-count-duration'), 10) || 1800;
    var decimals = el.hasAttribute('data-count-decimals')
      ? parseInt(el.getAttribute('data-count-decimals'), 10)
      : null;
    var prefix = el.getAttribute('data-count-prefix') || '';
    var suffix = el.getAttribute('data-count-suffix') || '';

    if (prefersReducedMotion()) {
      el.textContent = formatNumber(to, decimals, prefix, suffix);
      return;
    }

    var startTime = null;
    function step(timestamp) {
      if (!startTime) startTime = timestamp;
      var elapsed = timestamp - startTime;
      var t = Math.min(elapsed / duration, 1);
      var eased = easeOutExpo(t);
      var current = from + (to - from) * eased;
      el.textContent = formatNumber(current, decimals, prefix, suffix);
      if (t < 1) {
        window.requestAnimationFrame(step);
      } else {
        el.textContent = formatNumber(to, decimals, prefix, suffix);
      }
    }
    window.requestAnimationFrame(step);
  }

  function initCountUp() {
    var nodes = document.querySelectorAll('[data-count-to]');
    var reduceMotion = prefersReducedMotion();
    var viewOnce = false;

    function run(el) {
      if (el._countUpDone) return;
      el._countUpDone = true;
      countUp(el);
    }

    nodes.forEach(function (el) {
      var onlyWhenInView = el.getAttribute('data-count-view') === 'once';
      if (reduceMotion) {
        run(el);
        return;
      }
      if (onlyWhenInView) {
        var observer = new IntersectionObserver(
          function (entries) {
            entries.forEach(function (entry) {
              if (entry.isIntersecting) {
                run(entry.target);
                viewOnce = true;
              }
            });
          },
          { rootMargin: '0px 0px -50px 0px', threshold: 0.1 }
        );
        observer.observe(el);
      } else {
        run(el);
      }
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initCountUp);
  } else {
    initCountUp();
  }

  window.CountUp = { run: countUp, init: initCountUp, prefersReducedMotion: prefersReducedMotion };
})();
