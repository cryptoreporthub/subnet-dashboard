/** B1 UI — poll GET /api/data-freshness; sync header badge + LIVE pill (§27-1). */
(function () {
  'use strict';

  var BADGE_ID = 'dataFreshnessBadge';
  var PILL_ID = 'liveFeedPill';

  function formatCorrelationLocal(iso) {
    if (!iso) return null;
    var d = new Date(iso);
    if (isNaN(d.getTime())) return null;
    return d.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' });
  }

  function liveStatusLabel(prefix, iso) {
    var localTime = formatCorrelationLocal(iso);
    return localTime ? prefix + ' · ' + localTime : prefix;
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

  function effectiveMeta(payload) {
    var eff = payload.effective_source || 'blockmachine';
    var total =
      payload.effective_total != null
        ? payload.effective_total
        : payload.subnet_count || 0;
    return { eff: eff, total: total };
  }

  /** Single source of truth — pill + badge must match (§27-1). */
  function feedState(payload) {
    if (!payload || typeof payload !== 'object') return 'unknown';
    if (payload.ci_or_test || !payload.sync_enabled) return 'snapshot';

    var meta = effectiveMeta(payload);
    var eff = meta.eff;
    var total = meta.total;
    var chainLive =
      eff === 'blockmachine' && total > 0 && payload.last_sync && !payload.stale;

    if (chainLive) return 'live';
    if (eff === 'blockmachine' && payload.stale) return 'stale';
    if (total > 0 && eff !== 'none') return 'snapshot';
    if (!payload.last_sync) return 'warming';
    if (payload.stale) return 'stale';
    return 'snapshot';
  }

  function badgeLabel(payload, state) {
    if (!payload || typeof payload !== 'object') return 'Live';
    if (payload.ci_or_test) return 'Snapshot';
    if (!payload.sync_enabled) return 'Paused';

    var iso = payload.last_sync || null;

    if (state === 'live') return liveStatusLabel('Live', iso);
    if (state === 'stale') return liveStatusLabel('Stale', iso);
    if (state === 'warming') return 'Warming';
    if (state === 'snapshot') return liveStatusLabel('Snapshot', iso);
    return 'Live';
  }

  function render(payload) {
    var el = document.getElementById(BADGE_ID);
    var state = feedState(payload);

    applyLivePill(state);

    if (!el) return;
    applyBadge(el, state, badgeLabel(payload, state));
  }

  function ssrBootstrap() {
    var el = document.getElementById(BADGE_ID);
    var chip = document.getElementById('headerDataSource');
    if (!el) return;
    var raw = (chip && chip.textContent ? chip.textContent : '').trim().toLowerCase();
    if (raw && raw !== 'cache') {
      applyBadge(el, 'snapshot', 'Snapshot');
      applyLivePill('snapshot');
      return;
    }
    if (/loading/i.test(el.textContent || '')) {
      applyBadge(el, 'snapshot', 'Snapshot');
      applyLivePill('snapshot');
    }
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
            stale: false,
          });
          return;
        }
        render({
          sync_enabled: true,
          effective_source: 'registry-fallback',
          effective_total: 0,
          subnet_count: 0,
          ci_or_test: false,
        });
      });
  }

  // #1058: script tag sits before api_fetch.js — at defer evaluate readyState is
  // often interactive while afterHeroCritical is still undefined. Wait for DCL
  // (remaining deferred scripts, including the gate) then queue behind hero.
  function startPollWhenHeroReady() {
    if (window.afterHeroCritical) {
      window.afterHeroCritical(poll);
      return;
    }
    if (document.readyState === 'complete') {
      poll();
      return;
    }
    document.addEventListener('DOMContentLoaded', function onDclForFreshness() {
      document.removeEventListener('DOMContentLoaded', onDclForFreshness);
      if (window.afterHeroCritical) window.afterHeroCritical(poll);
      else poll();
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () {
      ssrBootstrap();
      startPollWhenHeroReady();
    });
  } else {
    ssrBootstrap();
    startPollWhenHeroReady();
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
