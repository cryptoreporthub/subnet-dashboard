/** Shared JSON fetch with hard timeout (single-worker Fly safety). */
(function (global) {
  'use strict';
  var inFlight = {};
  var responseCache = {};
  var DEFAULT_CACHE_MS = 15000;

  function fetchJson(url, ms, cacheMs) {
    var key = String(url);
    if (inFlight[key]) return inFlight[key];
    ms = ms == null ? 12000 : ms;
    cacheMs = cacheMs == null ? DEFAULT_CACHE_MS : Math.max(0, cacheMs);
    var cached = responseCache[key];
    if (cached && Date.now() - cached.at < cacheMs) {
      return Promise.resolve(cached.payload);
    }
    var ctrl = new AbortController();
    var timer = setTimeout(function () {
      ctrl.abort();
    }, ms);
    var request = fetch(url, {
      headers: { Accept: 'application/json' },
      signal: ctrl.signal,
      credentials: 'include',
    })
      .then(function (r) {
        clearTimeout(timer);
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.json();
      })
      .then(function (payload) {
        if (cacheMs > 0) responseCache[key] = { at: Date.now(), payload: payload };
        return payload;
      })
      .catch(function (err) {
        clearTimeout(timer);
        throw err;
      });
    inFlight[key] = request;
    request.then(
      function () { delete inFlight[key]; },
      function () { delete inFlight[key]; }
    );
    return request;
  }

  global.apiFetchJson = fetchJson;

  function fetchJsonRetry(url, ms, retries, cacheMs) {
    retries = retries == null ? 1 : retries;
    var lastErr;
    var attempt = 0;
    function tryOnce() {
      return fetchJson(url, ms + attempt * 4000, cacheMs);
    }
    return (function loop() {
      return tryOnce().catch(function (err) {
        lastErr = err;
        if (attempt >= retries) throw lastErr;
        attempt += 1;
        // Avoid synchronized retry storms when multiple panels hit a slow API.
        var delay = Math.min(1600, 250 * Math.pow(2, attempt - 1)) + Math.floor(Math.random() * 150);
        return new Promise(function (resolve) { setTimeout(resolve, delay); }).then(loop);
      });
    })();
  }

  global.apiFetchJsonRetry = fetchJsonRetry;
  global.apiFetchInvalidate = function (url) {
    if (url == null) {
      responseCache = {};
      inFlight = {};
      return;
    }
    var key = String(url);
    delete responseCache[key];
    delete inFlight[key];
  };
})(typeof window !== 'undefined' ? window : this);
