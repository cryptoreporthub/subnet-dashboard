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
    var sourceLabel = source;
    if (source === 'taomarketcap' || source === 'registry' || source === 'registry-fallback') {
      sourceLabel = source + ' (snapshot)';
    } else if (source === 'blockmachine' && feed.live_cache && feed.live_cache.stale) {
      sourceLabel = 'blockmachine (stale)';
    }
    var resOk = resolver.running ? 'resolver on' : 'resolver off';
    var ready = payload.ready;
    var alertCount = (whaleAlerts && whaleAlerts.total) || 0;
    var splitWeb =
      payload.worker_mode === 'split_v2' &&
      payload.worker_peer &&
      payload.worker_peer.expected;
    if (splitWeb && resolver.running) {
      resOk = 'resolver on (worker)';
    } else if (splitWeb && !resolver.running && payload.worker_peer.alive) {
      resOk = 'resolver check worker';
    }
    var webSnapshot = payload.worker_mode === 'web' && !resolver.running;
    if (webSnapshot && !ready) {
      el.hidden = true;
      return;
    }
    el.hidden = false;
    el.className =
      'ops-readiness-badge ' + (ready ? 'ops-readiness--ready' : 'ops-readiness--degraded');
    if (webSnapshot) {
      resOk = 'snapshot mode';
    }
    var line =
      graded + ' graded · ' + sourceLabel + (total ? ' · ' + total + ' SN' : '') + ' · ' + resOk;
    if (alertCount > 0) {
      line += ' · ' + alertCount + ' whale alert' + (alertCount === 1 ? '' : 's');
    }
    el.textContent = line;
    var tips = (payload.issues || []).slice();
    if (alertCount > 0 && whaleAlerts.rugger_alerts && whaleAlerts.rugger_alerts.length) {
      whaleAlerts.rugger_alerts.slice(0, 3).forEach(function (a) {
        tips.push('SN' + a.netuid + ' rug watch ~' + a.estimated_exit_in_hours + 'h');
      });
    }
    el.title = tips.join(', ') || 'Production readiness (/api/ops/readiness)';
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
