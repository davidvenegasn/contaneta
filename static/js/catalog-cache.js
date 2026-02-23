/**
 * P35: Cache en memoria (Map + TTL 10 min) para GET /api/catalogs/*, /api/customers, /api/products.
 * Uso: window.portalCatalogGetJson(url, { signal?: AbortSignal }) -> Promise<data>
 * Reduce loadings percibidos y evita requests duplicados.
 */
(function () {
  'use strict';
  var TTL_MS = 10 * 60 * 1000;
  var cache = new Map();
  var inFlight = new Map();

  function isCachedApiUrl(url) {
    if (!url || typeof url !== 'string') return false;
    var path = url.split('?')[0];
    return path.indexOf('/api/catalogs/') !== -1 ||
      path === '/api/customers' ||
      path === '/api/products';
  }

  function get(key) {
    var entry = cache.get(key);
    if (!entry) return null;
    if (Date.now() > entry.expires) {
      cache.delete(key);
      return null;
    }
    return entry.data;
  }

  function set(key, data) {
    cache.set(key, { data: data, expires: Date.now() + TTL_MS });
  }

  window.portalCatalogGetJson = function (url, options) {
    var fetcher = (typeof window.portalFetchWithTimeout === 'function')
      ? window.portalFetchWithTimeout
      : function (u, o) { return fetch(u, o); };
    if (!isCachedApiUrl(url)) {
      return fetcher(url, { credentials: 'same-origin', signal: options && options.signal }, 30000).then(function (r) {
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.json();
      });
    }
    var key = url;
    var cached = get(key);
    if (cached !== null) return Promise.resolve(cached);

    var pending = inFlight.get(key);
    if (pending) return pending;

    var signal = options && options.signal;
    var opts = { credentials: 'same-origin' };
    if (signal) opts.signal = signal;

    var promise = fetcher(url, opts, 30000)
      .then(function (r) {
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.json();
      })
      .then(function (data) {
        inFlight.delete(key);
        set(key, data);
        return data;
      })
      .catch(function (err) {
        inFlight.delete(key);
        throw err;
      });
    inFlight.set(key, promise);
    return promise;
  };
})();
