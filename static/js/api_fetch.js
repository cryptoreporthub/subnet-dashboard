/** Shared JSON fetch with hard timeout (single-worker Fly safety). */
(function (global) {
  'use strict';
  var inFlight = {};

  function fetchJson(url, ms) {
    var key = String(url);
    if (inFlight[key]) return inFlight[key];
    ms = ms == null ? 12000 : ms;
    var ctrl = new AbortController();
    var timer = setTimeout(function () {
      ctrl.abort();
    }, ms);
    var request = fetch(url, {
      headers: { Accept: 'application/json' },
      signal: ctrl.signal,
    })
      .then(function (r) {
        clearTimeout(timer);
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.json();
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

  function fetchJsonRetry(url, ms, retries) {
    retries = retries == null ? 1 : retries;
    var lastErr;
    var attempt = 0;
    function tryOnce() {
      return fetchJson(url, ms + attempt * 4000);
    }
    return (function loop() {
      return tryOnce().catch(function (err) {
        lastErr = err;
        if (attempt >= retries) throw lastErr;
        attempt += 1;
        return loop();
      });
    })();
  }

  global.apiFetchJsonRetry = fetchJsonRetry;
})(typeof window !== 'undefined' ? window : this);
