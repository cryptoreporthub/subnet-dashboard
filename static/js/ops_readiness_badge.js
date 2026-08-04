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
    payload = payload || {};
    var ready = payload.ready === true;
    var status = String(payload.status || '').toLowerCase();
    var issues = payload.issues || [];
    var issueCount = issues.length;
    var thin = payload.thin_ui_likely === true;

    var grade;
    var stateClass;
    if (ready && status === 'ready') {
      grade = 'READY';
      stateClass = 'ops-readiness--ready';
    } else if (thin || status === 'warming') {
      grade = 'WARMING';
      stateClass = 'ops-readiness--warming';
    } else {
      grade = 'DEGRADED';
      stateClass = 'ops-readiness--degraded';
    }

    el.hidden = false;
    el.textContent = grade;
    el.className = 'ops-readiness-badge ' + stateClass;
    if (issueCount) {
      el.title = grade + ' · ' + issueCount + ' issue(s): ' + issues.slice(0, 4).join(', ');
    } else {
      el.title = grade + ' · production readiness';
    }
  }

  function poll() {
    var el = document.getElementById('opsReadinessBadge');
    fetch('/api/ops/readiness', { headers: { Accept: 'application/json' } })
      .then(function (r) {
        if (!r.ok) throw new Error(String(r.status));
        return r.json();
      })
      .then(function (payload) {
        render(payload);
      })
      .catch(function () {
        if (el) {
          el.hidden = true;
          el.textContent = '';
        }
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
