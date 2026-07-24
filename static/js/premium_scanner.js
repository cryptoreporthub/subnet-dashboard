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

  /** Staking yield APY only — matches internal/subnets/apy.subnet_apy_percent */
  function apyOf(item) {
    var staking = item.staking_data;
    if (staking && staking.apy != null) {
      var frac = Number(staking.apy);
      if (!isNaN(frac)) return frac <= 1 ? frac * 100 : frac;
    }
    if (item.apy != null && item.id != null) {
      var raw = Number(item.apy);
      if (!isNaN(raw)) return raw <= 1 ? raw * 100 : raw;
    }
    return null;
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
      if (field === 'apy') { av = apyOf(a) || 0; bv = apyOf(b) || 0; }
      else if (field === 'emission') { av = a.emission || 0; bv = b.emission || 0; }
      else { av = a.id || a.netuid || 0; bv = b.id || b.netuid || 0; }
      return av - bv;
    });
    return items;
  }

  function chgOf(item) {
    var raw = item.price_change_24h != null ? item.price_change_24h : item.change_24h;
    if (raw == null) return null;
    var n = Number(raw);
    return isNaN(n) ? null : n;
  }

  function priceOf(item) {
    var raw = item.price != null ? item.price : item.token_price;
    if (raw == null) return null;
    var n = Number(raw);
    return isNaN(n) ? null : n;
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
      return '<tr class="scanner-row" data-netuid="' + esc(id) + '" tabindex="0" role="button" aria-label="Open report for ' + esc(item.name || 'SN' + id) + '">' +
        '<td>#' + esc(id) + '</td>' +
        '<td class="text-primary"><a href="/subnet/' + esc(id) + '" class="scanner-report-link">' + esc(item.name || 'Unnamed') + '</a></td>' +
        '<td><span class="badge ' + badge + '">' + esc(status) + '</span></td>' +
        '<td>' + fmt(item.emission, 3) + '</td>' +
        '<td>' + fmt(apyOf(item), 2) + '%</td>' +
        '<td>' + fmt(item.social_mentions, 0) + '</td>' +
        '</tr>';
    }).join('');
    var cards = items.map(function (item) {
      var id = item.netuid != null ? item.netuid : item.id;
      var chg = chgOf(item);
      var chgCls = chg == null ? '' : (chg >= 0 ? ' pos' : ' neg');
      var chgTxt = chg == null ? '—' : ((chg >= 0 ? '+' : '') + chg.toFixed(2) + '%');
      var price = priceOf(item);
      return '<div class="sr-matrix-card scanner-row" data-netuid="' + esc(id) + '" tabindex="0" role="button" aria-label="Open ' + esc(item.name || 'SN' + id) + '">' +
        '<span class="sr-matrix-card__name">' + esc(item.name || 'Unnamed') + '</span>' +
        '<span class="sr-matrix-card__price">' + (price != null ? fmt(price, 4) : '—') + '</span>' +
        '<span class="sr-matrix-card__sn">SN' + esc(id) + '</span>' +
        '<span class="sr-matrix-card__chg' + chgCls + '">' + chgTxt + ' 24h</span>' +
        '</div>';
    }).join('');
    tableEl.innerHTML =
      '<table class="tbl"><thead><tr><th>ID</th><th>Name</th><th>Status</th><th>Emission</th><th>APY</th><th>Social</th></tr></thead><tbody>' + rows + '</tbody></table>' +
      '<div class="sr-matrix-cards" aria-label="Subnet cards">' + cards + '</div>';
  }

  function load() {
    fetch('/api/subnets').then(function (r) { return r.json(); }).then(function (data) {
      var list = Array.isArray(data.subnets) ? data.subnets : data;
      if (Array.isArray(list)) {
        state.rows = list.map(function (item) {
          var row = Object.assign({}, item);
          row.id = row.id != null ? row.id : row.netuid;
          row.netuid = row.netuid != null ? row.netuid : row.id;
          return row;
        });
      } else {
        state.rows = Object.keys(list).map(function (key) {
          var item = Object.assign({}, list[key]);
          item.id = item.id != null ? item.id : Number(key);
          item.netuid = item.netuid != null ? item.netuid : item.id;
          return item;
        });
      }
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

  function openReport(netuid) {
    var id = parseInt(String(netuid), 10);
    if (!isNaN(id)) window.location.href = '/subnet/' + id;
  }

  tableEl.addEventListener('click', function (e) {
    if (e.target.closest('a.scanner-report-link')) return;
    var row = e.target.closest('.scanner-row');
    if (row) openReport(row.getAttribute('data-netuid'));
  });
  tableEl.addEventListener('keydown', function (e) {
    if (e.key !== 'Enter' && e.key !== ' ') return;
    var row = e.target.closest('.scanner-row');
    if (!row) return;
    e.preventDefault();
    openReport(row.getAttribute('data-netuid'));
  });

  load();
})();
