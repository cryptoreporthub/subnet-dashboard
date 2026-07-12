/* Premium subnet scanner — honest-empty, style.css tbl */
(function () {
  'use strict';

  var tableEl = document.getElementById('scanner-table');
  var metaEl = document.getElementById('scanner-meta');
  var searchEl = document.getElementById('scanner-search');
  var sortEl = document.getElementById('scanner-sort');
  var filterBar = document.getElementById('scanner-filters');
  if (!tableEl) return;

  var state = { rows: [], filter: 'all', search: '', sort: 'id' };

  function esc(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c];
    });
  }

  function fmt(n, d) {
    if (n === null || n === undefined || isNaN(n)) return '—';
    return Number(n).toLocaleString(undefined, { maximumFractionDigits: d || 2 });
  }

  function apyOf(item) {
    if (item.apy != null) return Number(item.apy) * 100;
    if (item.staking_data && item.staking_data.apy != null) return Number(item.staking_data.apy) * 100;
    return 0;
  }

  function filtered() {
    var items = state.rows.slice();
    if (state.filter !== 'all') {
      items = items.filter(function (i) {
        return String(i.status || 'unknown').toLowerCase() === state.filter;
      });
    }
    if (state.search.trim()) {
      var q = state.search.trim().toLowerCase();
      items = items.filter(function (i) {
        return String(i.id).includes(q) || String(i.netuid || i.id).includes(q) ||
          String(i.name || '').toLowerCase().includes(q);
      });
    }
    var field = state.sort;
    items.sort(function (a, b) {
      var av, bv;
      if (field === 'apy') { av = apyOf(a); bv = apyOf(b); }
      else if (field === 'emission') { av = a.emission || 0; bv = b.emission || 0; }
      else { av = a.id || a.netuid || 0; bv = b.id || b.netuid || 0; }
      return av - bv;
    });
    return items;
  }

  function render() {
    var items = filtered();
    if (metaEl) metaEl.textContent = items.length + ' subnet' + (items.length === 1 ? '' : 's');
    if (!items.length) {
      tableEl.innerHTML = '<p class="empty">No subnets match filters.</p>';
      return;
    }
    var rows = items.map(function (item) {
      var id = item.netuid != null ? item.netuid : item.id;
      var status = String(item.status || 'unknown').toLowerCase();
      var badge = status === 'active' ? 'badge-buy' : (status === 'deprecated' ? 'badge-sell' : 'badge-watch');
      return '<tr>' +
        '<td>#' + esc(id) + '</td>' +
        '<td class="text-primary">' + esc(item.name || 'Unnamed') + '</td>' +
        '<td><span class="badge ' + badge + '">' + esc(status) + '</span></td>' +
        '<td>' + fmt(item.emission, 3) + '</td>' +
        '<td>' + fmt(apyOf(item), 2) + '%</td>' +
        '<td>' + fmt(item.social_mentions, 0) + '</td>' +
        '</tr>';
    }).join('');
    tableEl.innerHTML = '<table class="tbl"><thead><tr><th>ID</th><th>Name</th><th>Status</th><th>Emission</th><th>APY</th><th>Social</th></tr></thead><tbody>' + rows + '</tbody></table>';
  }

  function load() {
    fetch('/api/registry').then(function (r) { return r.json(); }).then(function (data) {
      state.rows = Object.keys(data).map(function (key) {
        var item = Object.assign({}, data[key]);
        item.id = item.id != null ? item.id : Number(key);
        item.netuid = item.netuid != null ? item.netuid : item.id;
        return item;
      });
      render();
    }).catch(function () {
      tableEl.innerHTML = '<p class="empty">Scanner warming up — registry API unreachable on this deploy.</p>';
      if (metaEl) metaEl.textContent = 'unavailable';
    });
  }

  if (filterBar) {
    filterBar.addEventListener('click', function (e) {
      var btn = e.target.closest('.tab-btn');
      if (!btn) return;
      filterBar.querySelectorAll('.tab-btn').forEach(function (b) { b.classList.remove('active'); });
      btn.classList.add('active');
      state.filter = btn.getAttribute('data-filter') || 'all';
      render();
    });
  }
  if (searchEl) searchEl.addEventListener('input', function () { state.search = searchEl.value; render(); });
  if (sortEl) sortEl.addEventListener('change', function () { state.sort = sortEl.value; render(); });

  load();
})();
