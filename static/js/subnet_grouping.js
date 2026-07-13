/* Optional lane — per-subnet grouping / collapse (frontend-only) */
(function () {
  'use strict';

  var dataEl = document.getElementById('subnet-group-data');
  var rootEl = document.getElementById('subnet-groups-root');
  if (!dataEl || !rootEl) return;

  var STORAGE_PREFIX = 'subnet-group-open-'; // persisted open state per netuid

  function esc(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c];
    });
  }

  function subnetKey(row) {
    if (!row) return null;
    var n = row.netuid != null ? row.netuid : row.id;
    return n == null ? null : Number(n);
  }

  function parseData() {
    try {
      return JSON.parse(dataEl.textContent);
    } catch (e) {
      return null;
    }
  }

  function buildGroups(data) {
    var groups = {};
    (data.roster || []).forEach(function (sn) {
      var key = subnetKey(sn);
      if (key == null) return;
      groups[key] = {
        meta: sn,
        indicators: [],
        hour_picks: [],
        day_picks: [],
        trail: [],
        predictions: [],
      };
    });

    function assign(list, field) {
      (list || []).forEach(function (row) {
        var key = subnetKey(row);
        if (key == null) return;
        if (!groups[key]) {
          groups[key] = {
            meta: row,
            indicators: [],
            hour_picks: [],
            day_picks: [],
            trail: [],
            predictions: [],
          };
        }
        groups[key][field].push(row);
      });
    }

    assign(data.indicators, 'indicators');
    assign(data.hour_picks, 'hour_picks');
    assign(data.day_picks, 'day_picks');
    assign(data.predictions, 'predictions');

    (data.trail || []).forEach(function (row) {
      var key = subnetKey(row);
      if (key != null && groups[key]) {
        groups[key].trail.push(row);
        return;
      }
      if (!row.subnet) return;
      Object.keys(groups).forEach(function (k) {
        var g = groups[k];
        if (g.meta && g.meta.name === row.subnet) g.trail.push(row);
      });
    });

    return groups;
  }

  function signalCount(g) {
    return (
      g.indicators.length +
      g.hour_picks.length +
      g.day_picks.length +
      g.trail.length +
      g.predictions.length
    );
  }

  function renderChild(label, text) {
    return (
      '<div class="subnet-group-item">' +
      '<span class="subnet-group-item-label">' + esc(label) + '</span>' +
      '<span class="subnet-group-item-val">' + esc(text) + '</span>' +
      '</div>'
    );
  }

  function renderGroup(key, g) {
    var meta = g.meta || {};
    var name = meta.name || ('SN' + key);
    var id = subnetKey(meta) || key;
    var count = signalCount(g);
    if (count === 0) return '';

    var open = localStorage.getItem(STORAGE_PREFIX + key) === '1';
    var items = '';

    g.indicators.forEach(function (row) {
      var os = row.oversold || {};
      var ob = row.overbought || {};
      var parts = [];
      if (os.convergent) parts.push('OVERSOLD ' + (os.count || 0) + '/' + (os.total || 0));
      if (ob.convergent) parts.push('OVERBOUGHT ' + (ob.count || 0) + '/' + (ob.total || 0));
      if (!parts.length) parts.push('NEUTRAL');
      items += renderChild('Indicators', parts.join(' · '));
    });
    g.hour_picks.forEach(function (row) {
      items += renderChild(
        'Hour pick',
        'score ' + Number(row.score || 0).toFixed(1) +
          ' · conf ' + (Number(row.confidence || 0) * 100).toFixed(0) + '%'
      );
    });
    g.day_picks.forEach(function (row) {
      items += renderChild(
        'Day pick',
        'score ' + Number(row.score || 0).toFixed(1) +
          ' · conf ' + (Number(row.confidence || 0) * 100).toFixed(0) + '%'
      );
    });
    g.trail.forEach(function (row) {
      items += renderChild('Trail', (row.signal || '—') + ' → ' + (row.decision || '—'));
    });
    g.predictions.forEach(function (row) {
      items += renderChild('Prediction', row.statement || row.status || 'pending');
    });

    var status = String(meta.status || 'unknown');
    var badge =
      status === 'active' ? 'badge-buy' : status === 'deprecated' ? 'badge-sell' : 'badge-watch';

    return (
      '<details class="subnet-group card" data-subnet-key="' + id + '"' + (open ? ' open' : '') + '>' +
      '<summary class="subnet-group-summary">' +
      '<span class="subnet-group-caret" aria-hidden="true"></span>' +
      '<span class="pick-name">' + esc(name) + '</span>' +
      '<span class="pick-meta">SN' + id + '</span>' +
      '<span class="badge ' + badge + '">' + esc(status) + '</span>' +
      '<span class="subnet-group-count">' + count + ' signal' + (count === 1 ? '' : 's') + '</span>' +
      '</summary>' +
      '<div class="subnet-group-body">' + items + '</div>' +
      '</details>'
    );
  }

  function init() {
    var data = parseData();
    if (!data) {
      rootEl.innerHTML = '<p class="empty">Subnet rollup unavailable — context payload missing.</p>';
      return;
    }

    var groups = buildGroups(data);
    var keys = Object.keys(groups)
      .map(Number)
      .sort(function (a, b) {
        var ea = (groups[a].meta && groups[a].meta.emission) || 0;
        var eb = (groups[b].meta && groups[b].meta.emission) || 0;
        return eb - ea;
      });

    var html = keys.map(function (k) { return renderGroup(k, groups[k]); }).filter(Boolean).join('');
    if (!html) {
      rootEl.innerHTML =
        '<p class="empty">Subnet rollup warming up — signals appear as indicators, picks, and trail events populate.</p>';
      return;
    }

    rootEl.innerHTML = html;
    rootEl.querySelectorAll('details.subnet-group').forEach(function (el) {
      el.addEventListener('toggle', function () {
        var key = el.getAttribute('data-subnet-key');
        if (!key) return;
        localStorage.setItem(STORAGE_PREFIX + key, el.open ? '1' : '0');
      });
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  window.__refreshSubnetGroups = init;
})();
