/** §31-7 — lazy-load non-core home scripts on drawer open */
(function () {
  'use strict';

  var loaded = {};
  var DEFERRED = [
    '/static/vendor/uplot/uPlot.iife.min.js',
    '/static/js/uplot_charts.js',
    '/static/js/data_freshness.js',
    '/static/js/conviction_tiers.js',
    '/static/js/premium_signals.js',
    '/static/js/market_drivers_ui.js',
    '/static/js/trust_banner_ui.js',
    '/static/js/story_path_ui.js',
    '/static/js/time_capsule.js',
    '/static/js/brain_letter.js',
    '/static/js/watchlist_alerts.js',
    '/static/js/paper_portfolio.js',
    '/static/js/letter_export.js',
    '/static/js/weekly_letter.js',
    '/static/js/daily_recap.js',
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

  function loadDeferred() {
    return DEFERRED.reduce(function (chain, src) {
      return chain.then(function () { return loadScript(src); });
    }, Promise.resolve());
  }

  function bindDrawer(id) {
    var el = document.getElementById(id);
    if (!el) return;
    el.addEventListener('toggle', function () {
      if (el.open) loadDeferred().catch(function () {});
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    bindDrawer('pro-cockpit');
    bindDrawer('market-drawer');
    setTimeout(function () { loadDeferred().catch(function () {}); }, 4000);
  });

  window.HomeDeferredScripts = { load: loadDeferred };
})();
