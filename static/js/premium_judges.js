/* Judge council cards — lazy load when Pro cockpit opens (§29-8) */
(function () {
  'use strict';

  var panel = document.getElementById('judges-panel');
  var drawer = document.getElementById('pro-cockpit');
  if (!panel) return;

  var loaded = false;
  var FETCH_MS = 18000;

  function esc(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c];
    });
  }

  function verdictClass(v) {
    if (v === 'bullish' || v === 'long') return 'badge-buy';
    if (v === 'bearish' || v === 'short') return 'badge-sell';
    return 'badge-watch';
  }

  function focusNetuid() {
    if (window.LivingFocus && window.LivingFocus.netuid != null) {
      return window.LivingFocus.netuid;
    }
    var root = document.getElementById('section-living-focus');
    if (root && root.getAttribute('data-focus-netuid')) {
      return Number(root.getAttribute('data-focus-netuid'));
    }
    return null;
  }

  function alreadyRendered() {
    return !!(panel.querySelector('.judge-summary') || panel.querySelector('.kpi-grid'));
  }

  function judgeCard(j, opts) {
    opts = opts || {};
    var verdict = (j.consensus && j.consensus.verdict) || 'neutral';
    var score = j.consensus ? j.consensus.score : null;
    var oracle = j.oracle ? j.oracle.score.toFixed(2) : '—';
    var echo = j.echo ? j.echo.score.toFixed(2) : '—';
    var pulse = j.pulse ? j.pulse.score.toFixed(2) : '—';
    var title = opts.link
      ? '<a href="/subnet/' + esc(j.netuid) + '">' + esc(j.name || ('SN' + j.netuid)) + '</a>'
      : esc(j.name || ('SN' + j.netuid));
    var meta = 'SN' + esc(j.netuid) + (score != null ? ' · consensus ' + Number(score).toFixed(2) : '');
    if (opts.focus) meta += ' · Living Focus';
    return '<article class="card judge-summary" style="margin-bottom:10px;">' +
      '<div class="card-head"><h3>' + title + '</h3>' +
      '<span class="badge ' + verdictClass(verdict) + '">' + esc(String(verdict).toUpperCase()) + '</span></div>' +
      '<div class="pick-meta">' + meta + '</div>' +
      '<div class="kpi-grid" style="grid-template-columns:repeat(3,1fr);margin-top:8px;">' +
      '<div class="kpi-cell"><div class="k">Oracle</div><div class="v">' + oracle + '</div></div>' +
      '<div class="kpi-cell"><div class="k">Echo</div><div class="v">' + echo + '</div></div>' +
      '<div class="kpi-cell"><div class="k">Pulse</div><div class="v">' + pulse + '</div></div>' +
      '</div></article>';
  }

  function renderLeague(judges) {
    if (!judges.length) {
      panel.innerHTML = '<p class="empty empty--quiet">Quiet — no lane judge scores yet. Council scoring warms after subnet snapshots load.</p>';
      return;
    }
    var cards = judges.slice(0, 12).map(function (j) {
      return judgeCard(j, { link: true });
    }).join('');
    panel.innerHTML = '<div class="picks">' + cards + '</div>' +
      '<p class="pick-meta" style="margin-top:8px;">' + judges.length + ' subnets scored</p>';
  }

  function fetchJson(url, ms) {
    return new Promise(function (resolve, reject) {
      var ctrl = new AbortController();
      var timer = setTimeout(function () {
        ctrl.abort();
        reject(new Error('timeout'));
      }, ms);
      fetch(url, { headers: { Accept: 'application/json' }, signal: ctrl.signal })
        .then(function (r) {
          clearTimeout(timer);
          if (!r.ok) throw new Error(String(r.status));
          return r.json();
        })
        .then(resolve)
        .catch(function (err) {
          clearTimeout(timer);
          reject(err);
        });
    });
  }

  function loadJudges() {
    if (loaded || alreadyRendered()) {
      loaded = true;
      return;
    }
    loaded = true;
    panel.innerHTML = '<p class="empty">Building — lane judges loading…</p>';
    var focus = focusNetuid();
    var url = focus != null ? '/api/judges/' + encodeURIComponent(focus) : '/api/judges';
    fetchJson(url, FETCH_MS)
      .then(function (data) {
        if (focus != null && data && !data.error) {
          panel.innerHTML = judgeCard(data, { focus: true });
          return;
        }
        renderLeague((data && data.judges) || []);
      })
      .catch(function () {
        panel.innerHTML = '<p class="empty empty--quiet">Quiet — lane judges unavailable. Retry when /api/judges responds.</p>';
        loaded = false;
      });
  }

  if (drawer) {
    drawer.addEventListener('toggle', function () {
      if (drawer.open) loadJudges();
    });
  } else {
    loadJudges();
  }

  document.addEventListener('living-focus:change', function () {
    if (!drawer || !drawer.open) return;
    loaded = false;
    loadJudges();
  });
})();
