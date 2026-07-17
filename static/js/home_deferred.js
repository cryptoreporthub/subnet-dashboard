/** §34-1 — load above-fold data scripts immediately; heavy tools on drawer / idle */
(function () {
  'use strict';

  var loaded = {};

  /** First-viewport + Pro-visible data UIs — must not wait 4s */
  var ABOVE_FOLD = [
    '/static/js/data_freshness.js',
    '/static/js/ops_readiness_badge.js',
    '/static/js/conviction_tiers.js',
    '/static/js/trust_banner_ui.js',
    '/static/js/market_drivers_ui.js',
    '/static/js/brain_letter.js',
    '/static/js/story_path_ui.js',
    '/static/js/paper_portfolio.js',
    '/static/js/weekly_letter.js',
    '/static/js/daily_recap.js',
    '/static/js/watchlist_alerts.js',
    '/static/js/letter_export.js',
    '/static/js/time_capsule.js',
  ];

  /** Heavy / drawer-only — load on open or idle */
  var DEFERRED = [
    '/static/vendor/uplot/uPlot.iife.min.js',
    '/static/js/uplot_charts.js',
    '/static/js/premium_signals.js',
    '/static/js/subnet_grouping.js',
    '/static/js/premium_scanner.js',
    '/static/js/investigation_panel.js',
    '/static/js/premium_judges.js',
    '/static/js/subnet_report.js',
    '/static/js/message_intel_feed.js',
    '/static/js/social_sentiment.js',
  ];

  function loadScript(src) {
    if (loaded[src]) return loaded[src];
    loaded[src] = new Promise(function (resolve, reject) {
      var el = document.createElement('script');
      el.src = src;
      el.defer = true;
      el.onload = function () { resolve(); };
      el.onerror = function () { reject(new Error('load failed: ' + src)); };
      document.body.appendChild(el);
    });
    return loaded[src];
  }

  function loadList(list) {
    return list.reduce(function (chain, src) {
      return chain.then(function () { return loadScript(src); });
    }, Promise.resolve());
  }

  function loadAboveFold() {
    return loadList(ABOVE_FOLD);
  }

  function loadDeferred() {
    return loadList(DEFERRED);
  }

  function loadAll() {
    return loadAboveFold().then(function () { return loadDeferred(); });
  }

  function bindDrawer(id) {
    var el = document.getElementById(id);
    if (!el) return;
    el.addEventListener('toggle', function () {
      if (el.open) loadAll().catch(function () {});
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    bindDrawer('pro-cockpit');
    bindDrawer('market-drawer');
    // Real data on first paint — do not wait 4s
    loadAboveFold().catch(function () {});
    // Heavy tools: idle or 2s (not 4s)
    var idle = window.requestIdleCallback || function (cb) { setTimeout(cb, 2000); };
    idle(function () { loadDeferred().catch(function () {}); }, { timeout: 2500 });
  });

  window.HomeDeferredScripts = { load: loadAll, loadAboveFold: loadAboveFold };
})();
