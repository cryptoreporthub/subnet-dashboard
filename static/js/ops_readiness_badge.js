/** §34-1 — one-line ops readiness next to freshness (graded / feed / resolver). */
(function () {
  'use strict';

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c];
    });
  }

  function render(payload) {
    var el = document.getElementById('opsReadinessBadge');
    if (!el) return;
    if (!payload || typeof payload !== 'object') {
      el.textContent = 'Ops: unavailable';
      el.className = 'ops-readiness-badge ops-readiness--unknown';
      return;
    }
    var learning = payload.learning || {};
    var feed = payload.subnet_feed || {};
    var resolver = payload.resolver || {};
    var graded = learning.graded != null ? learning.graded : 0;
    var source = feed.effective_source || 'none';
    var total = feed.likely_total != null ? feed.likely_total : 0;
    var resOk = resolver.running ? 'resolver on' : 'resolver off';
    var ready = payload.ready;
    el.className =
      'ops-readiness-badge ' + (ready ? 'ops-readiness--ready' : 'ops-readiness--degraded');
    el.textContent =
      graded + ' graded · ' + source + (total ? ' · ' + total + ' SN' : '') + ' · ' + resOk;
    el.title = (payload.issues || []).join(', ') || 'Production readiness (/api/ops/readiness)';
  }

  function poll() {
    fetch('/api/ops/readiness', { headers: { Accept: 'application/json' } })
      .then(function (r) {
        if (!r.ok) throw new Error(String(r.status));
        return r.json();
      })
      .then(render)
      .catch(function () {
        render(null);
      });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', poll);
  } else {
    poll();
  }
  setInterval(poll, 120000);
})();
