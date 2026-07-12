/* Judge council cards — /api/judges, style.css judge-summary */
(function () {
  'use strict';

  var panel = document.getElementById('judges-panel');
  if (!panel) return;

  function esc(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c];
    });
  }

  function verdictClass(v) {
    if (v === 'bullish') return 'badge-buy';
    if (v === 'bearish') return 'badge-sell';
    return 'badge-watch';
  }

  fetch('/api/judges')
    .then(function (r) { return r.json(); })
    .then(function (data) {
      var judges = (data && data.judges) || [];
      if (!judges.length) {
        panel.innerHTML = '<p class="empty">No judge data yet — council scoring warms up after subnet snapshots load.</p>';
        return;
      }
      var cards = judges.slice(0, 12).map(function (j) {
        var verdict = (j.consensus && j.consensus.verdict) || 'neutral';
        var score = j.consensus ? j.consensus.score : null;
        var oracle = j.oracle ? j.oracle.score.toFixed(2) : '—';
        var echo = j.echo ? j.echo.score.toFixed(2) : '—';
        var pulse = j.pulse ? j.pulse.score.toFixed(2) : '—';
        return '<article class="card judge-summary" style="margin-bottom:10px;">' +
          '<div class="card-head"><h3>' + esc(j.name || ('SN' + j.netuid)) + '</h3>' +
          '<span class="badge ' + verdictClass(verdict) + '">' + esc(String(verdict).toUpperCase()) + '</span></div>' +
          '<div class="pick-meta">SN' + esc(j.netuid) + (score != null ? ' · consensus ' + score.toFixed(2) : '') + '</div>' +
          '<div class="kpi-grid" style="grid-template-columns:repeat(3,1fr);margin-top:8px;">' +
          '<div class="kpi-cell"><div class="k">Oracle</div><div class="v">' + oracle + '</div></div>' +
          '<div class="kpi-cell"><div class="k">Echo</div><div class="v">' + echo + '</div></div>' +
          '<div class="kpi-cell"><div class="k">Pulse</div><div class="v">' + pulse + '</div></div>' +
          '</div></article>';
      }).join('');
      panel.innerHTML = '<div class="picks">' + cards + '</div>' +
        '<p class="pick-meta" style="margin-top:8px;">' + judges.length + ' subnets scored</p>';
    })
    .catch(function () {
      panel.innerHTML = '<p class="empty">Judge panel warming up — /api/judges unreachable on this deploy.</p>';
    });
})();
