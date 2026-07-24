/** B1 UI — poll GET /api/data-freshness; sync header badge + LIVE pill (§27-1). */
(function () {
  'use strict';

  var BADGE_ID = 'dataFreshnessBadge';
  var PILL_ID = 'liveFeedPill';

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

  function applyLivePill(state) {
    var el = document.getElementById(PILL_ID);
    if (!el) return;
    var label = 'LIVE';
    var cls = 'live-pill live-pill--live';
    if (state === 'stale') {
      label = 'STALE';
      cls = 'live-pill live-pill--stale';
    } else if (state === 'snapshot' || state === 'warming') {
      label = 'SNAPSHOT';
      cls = 'live-pill live-pill--snapshot';
    } else if (state === 'unknown') {
      label = 'OFFLINE';
      cls = 'live-pill live-pill--offline';
    }
    el.className = cls;
    el.innerHTML = '<span class="live-dot" aria-hidden="true"></span>' + label;
  }

  function feedState(payload) {
    if (!payload || typeof payload !== 'object') return 'unknown';
    if (payload.ci_or_test || !payload.sync_enabled) return 'snapshot';
    // Prefer effective feed (TMC / registry) over empty blockmachine cache
    var eff = payload.effective_source;
    var total = payload.effective_total != null ? payload.effective_total : payload.subnet_count;
    if (eff && eff !== 'none' && total > 0) {
      if (eff === 'blockmachine' && !payload.stale) return 'live';
      if (eff === 'blockmachine' && payload.stale) return 'stale';
      return 'snapshot'; // taomarketcap / registry — honest live economics
    }
    if (!payload.last_sync) return 'warming';
    if (payload.stale) return 'stale';
    return 'live';
  }

  function render(payload) {
    var el = document.getElementById(BADGE_ID);
    var state = feedState(payload);

    applyLivePill(state);

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
    var eff = payload.effective_source || 'blockmachine';
    var count =
      payload.effective_total != null
        ? payload.effective_total
        : payload.subnet_count || 0;

    // Blockmachine cache empty but TMC/registry serving — show real feed, not "loading"
    if ((!payload.last_sync || payload.subnet_count === 0) && count > 0 && eff !== 'blockmachine') {
      applyBadge(el, 'snapshot', eff + ' · ' + count + ' subnets');
      return;
    }

    if (!payload.last_sync) {
      applyBadge(el, 'warming', 'Chain feed: warming up');
      return;
    }

    if (payload.stale) {
      applyBadge(
        el,
        'stale',
        'Stale chain · ' + (age || 'unknown') + (count ? ' · feed ' + count + ' SN' : '')
      );
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
        var cache = window.HomeHydrateCache;
        if (cache && cache.subnets && cache.subnets.length) {
          render({
            sync_enabled: true,
            effective_source: (cache.subnetsMeta && cache.subnetsMeta.source) || 'taomarketcap',
            effective_total: cache.subnets.length,
            subnet_count: 0,
            last_sync: null,
          });
          return;
        }
        render({ sync_enabled: true, effective_source: 'registry-fallback', effective_total: 0, subnet_count: 0 });
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
  setInterval(tick, 60000);
})();
