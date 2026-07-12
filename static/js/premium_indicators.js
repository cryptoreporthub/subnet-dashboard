/* Premium indicator lanes — per-subnet signal groups with collapse + live refresh */
(function () {
  'use strict';

  var grid = document.getElementById('indicator-lanes');
  if (!grid) return;

  var collapsed = new Set();
  var POLL_MS = 60000;

  function esc(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c];
    });
  }

  function heatTier(pct) {
    if (pct > 66) return 'high';
    if (pct > 33) return 'core';
    return 'low';
  }

  function signalRows(row, perSubnet) {
    var items = [];
    var os = row.oversold || {};
    var ob = row.overbought || {};
    var osTotal = os.total || 7;
    var obTotal = ob.total || 7;

    if (os.convergent) {
      items.push({
        name: 'Oversold',
        value: (os.count || 0) + '/' + (os.total || 0),
        tier: 'low',
        pct: Math.min(100, Math.round(((os.count || 0) / osTotal) * 100))
      });
    }
    if (ob.convergent) {
      items.push({
        name: 'Overbought',
        value: (ob.count || 0) + '/' + (ob.total || 0),
        tier: 'high',
        pct: Math.min(100, Math.round(((ob.count || 0) / obTotal) * 100))
      });
    }
    if (!items.length) {
      items.push({ name: 'Convergence', value: 'neutral', tier: 'core', pct: 20 });
    }

    var ps = (perSubnet && perSubnet[String(row.netuid)]) || {};
    (ps.active_signals || []).forEach(function (ev) {
      items.push({
        name: String(ev).replace(/_/g, ' '),
        value: 'active',
        tier: 'core',
        pct: 55
      });
    });
    if (ps.rsi != null && !isNaN(ps.rsi)) {
      var rsi = Number(ps.rsi);
      items.push({
        name: 'RSI',
        value: rsi.toFixed(1),
        tier: rsi > 70 ? 'high' : (rsi < 30 ? 'low' : 'core'),
        pct: Math.min(100, Math.round(rsi))
      });
    }
    return items;
  }

  function renderItems(items) {
    return items.map(function (it) {
      return '<div class="vol-cluster-item">' +
        '<span class="vol-cluster-name">' + esc(it.name) + '</span>' +
        '<div class="vol-cluster-bar-wrap">' +
        '<div class="vol-cluster-bar vol-bar-' + it.tier + '" style="width:' + it.pct + '%;"></div>' +
        '</div>' +
        '<span class="vol-cluster-value">' + esc(it.value) + '</span>' +
        '</div>';
    }).join('');
  }

  function bindToggles() {
    grid.querySelectorAll('.lane-toggle').forEach(function (btn) {
      if (btn.dataset.bound) return;
      btn.dataset.bound = '1';
      btn.addEventListener('click', function () {
        var group = btn.closest('.vol-cluster-group');
        if (!group) return;
        var id = group.getAttribute('data-netuid');
        var isCollapsed = group.classList.toggle('is-collapsed');
        btn.setAttribute('aria-expanded', isCollapsed ? 'false' : 'true');
        if (isCollapsed) collapsed.add(id);
        else collapsed.delete(id);
      });
    });
  }

  function applyLane(group, row, perSubnet) {
    var items = signalRows(row, perSubnet);
    var countEl = group.querySelector('.vol-cluster-count');
    var itemsEl = group.querySelector('.vol-cluster-items');
    if (countEl) countEl.textContent = String(items.length);
    if (itemsEl) itemsEl.innerHTML = renderItems(items);

    var os = row.oversold || {};
    var ob = row.overbought || {};
    var heat = (os.count || 0) + (ob.count || 0);
    var heatPct = Math.round((heat / (os.total || 7)) * 100);
    var tier = heatTier(heatPct);
    var dot = group.querySelector('.vol-cluster-dot');
    if (dot) dot.className = 'vol-cluster-dot vol-dot-' + tier;
    var heatBar = group.querySelector('.lane-heat-bar');
    if (heatBar) {
      heatBar.style.width = Math.min(100, heatPct) + '%';
      heatBar.className = 'vol-cluster-bar lane-heat-bar vol-bar-' + tier;
    }
    var heatVal = group.querySelector('.lane-heat-value');
    if (heatVal) heatVal.textContent = heatPct + '%';
  }

  function refresh() {
    Promise.all([
      fetch('/api/indicators-convergence').then(function (r) { return r.json(); }),
      fetch('/api/indicators').then(function (r) { return r.json(); })
    ]).then(function (res) {
      var conv = res[0].subnets || [];
      var perSubnet = (((res[1] || {}).data || {}).per_subnet) || {};
      conv.slice(0, 6).forEach(function (row) {
        var group = grid.querySelector('[data-netuid="' + row.netuid + '"]');
        if (group) applyLane(group, row, perSubnet);
      });
    }).catch(function () { /* keep SSR snapshot */ });
  }

  grid.querySelectorAll('.vol-cluster-group.is-collapsed').forEach(function (g) {
    collapsed.add(g.getAttribute('data-netuid'));
  });

  bindToggles();
  setInterval(refresh, POLL_MS);
})();
