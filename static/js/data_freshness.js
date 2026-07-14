/** B1 UI — poll GET /api/data-freshness and update the header badge (audit #1). */
(function () {
  'use strict';

  var BADGE_ID = 'dataFreshnessBadge';

  function formatAge(seconds) {
    if (seconds == null || seconds < 0) return null;
    if (seconds < 60) return seconds + 's ago';
    if (seconds < 3600) return Math.floor(seconds / 60) + 'm ago';
    if (seconds < 86400) return Math.floor(seconds / 3600) + 'h ago';
    return Math.floor(seconds / 86400) + 'd ago';
  }

  function applyBadge(el, state, label) {
    el.className = 'data-freshness-badge data-freshness-' + state;
    el.textContent = label;
    el.setAttribute('title', 'On-chain subnet feed freshness (/api/data-freshness)');
  }

  function render(payload) {
    var el = document.getElementById(BADGE_ID);
    if (!el) return;

    if (!payload || typeof payload !== 'object') {
      applyBadge(el, 'unknown', 'Feed: unavailable');
      return;
    }

    if (payload.ci_or_test) {
      applyBadge(el, 'snapshot', 'Data: registry snapshot');
      return;
    }

    if (!payload.sync_enabled) {
      applyBadge(el, 'snapshot', 'Data: sync paused');
      return;
    }

    var age = formatAge(payload.age_seconds);
    var count = payload.subnet_count || 0;

    if (!payload.last_sync) {
      applyBadge(el, 'warming', 'Chain feed: warming up');
      return;
    }

    if (payload.stale) {
      applyBadge(el, 'stale', 'Stale · ' + (age || 'unknown') + ' · ' + count + ' subnets');
      return;
    }

    applyBadge(el, 'live', 'Live · ' + (age || 'just now') + ' · ' + count + ' subnets');
  }

  function poll() {
    fetch('/api/data-freshness', { headers: { Accept: 'application/json' } })
      .then(function (r) {
        if (!r.ok) throw new Error('HTTP ' + r.status);
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

  setInterval(poll, 60000);
})();
