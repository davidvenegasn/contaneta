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
    var fetcher = (typeof window.portalFetchJSON === 'function')
      ? function (u, o) {
        return window.portalFetchJSON(u, o, { timeoutMs: 30000, retry: 1 }).then(function (r) {
          if (r && r.ok) {
            // portalFetchJSON devuelve { ok:true, data:<body> }. Si el body usa {ok:true,data:...}, desempaquetar.
            var body = r.data;
            if (body && typeof body === 'object' && body.ok === true && Object.prototype.hasOwnProperty.call(body, 'data')) return body.data;
            return body;
          }
          var e = new Error((r && r.detail) || ('HTTP ' + ((r && r.status) || 0)));
          if (r && r.error === 'timeout') e.isTimeout = true;
          throw e;
        });
      }
      : function (u, o) {
        return fetch(u, o).then(function (r) {
          if (!r.ok) throw new Error('HTTP ' + r.status);
          return r.json().then(function (body) {
            if (body && typeof body === 'object' && body.ok === true && Object.prototype.hasOwnProperty.call(body, 'data')) return body.data;
            return body;
          });
        });
      };
    if (!isCachedApiUrl(url)) {
      return fetcher(url, { credentials: 'same-origin', signal: options && options.signal });
    }
    var key = url;
    var cached = get(key);
    if (cached !== null) return Promise.resolve(cached);

    var pending = inFlight.get(key);
    if (pending) return pending;

    var signal = options && options.signal;
    var opts = { credentials: 'same-origin' };
    if (signal) opts.signal = signal;

    var promise = fetcher(url, opts)
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
