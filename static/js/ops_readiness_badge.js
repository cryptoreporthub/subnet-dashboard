/** §34-1 — one-line ops readiness next to freshness (graded / feed / resolver). */
(function () {
  'use strict';

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c];
    });
  }

  function render(payload, whaleAlerts) {
    var el = document.getElementById('opsReadinessBadge');
    if (!el) return;
    el.hidden = true;
    el.textContent = '';
    el.removeAttribute('title');
  }

  function poll() {
    Promise.all([
      fetch('/api/ops/readiness', { headers: { Accept: 'application/json' } }).then(function (r) {
        if (!r.ok) throw new Error(String(r.status));
        return r.json();
      }),
      fetch('/api/whales/alerts', { headers: { Accept: 'application/json' } })
        .then(function (r) { return r.ok ? r.json() : null; })
        .catch(function () { return null; }),
    ])
      .then(function (res) { render(res[0], res[1]); })
      .catch(function () {
        el.hidden = true;
      });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', poll);
  } else {
    poll();
  }
  function tick() {
    if (document.visibilityState === 'hidden') return;
    poll();
  }
  document.addEventListener('visibilitychange', function () {
    if (document.visibilityState === 'visible') tick();
  });
  setInterval(tick, 120000);
})();
