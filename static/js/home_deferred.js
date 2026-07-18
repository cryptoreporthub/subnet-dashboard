/** §34-1 — heavy drawer tools only; above-fold data scripts are static in scripts.html */
(function () {
  'use strict';

  var loaded = {};

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
    if (document.querySelector('script[src="' + src + '"]')) {
      loaded[src] = Promise.resolve();
      return loaded[src];
    }
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
      return chain
        .then(function () { return loadScript(src); })
        .catch(function (err) {
          console.warn('[home_deferred] skip', src, err);
        });
    }, Promise.resolve());
  }

  function loadDeferred() {
    return loadList(DEFERRED);
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
    var idle = window.requestIdleCallback || function (cb) { setTimeout(cb, 2000); };
    idle(function () { loadDeferred().catch(function () {}); }, { timeout: 2500 });
  });

  window.HomeDeferredScripts = { load: loadDeferred, loadDeferred: loadDeferred };
})();
