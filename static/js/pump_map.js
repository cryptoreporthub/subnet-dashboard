(function () {
  'use strict';

  function esc(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c];
    });
  }

  function isBoardMode() {
    return !!document.querySelector('[data-pump-compact="1"]');
  }

  function readRows() {
    var el = document.getElementById('pump-map-data');
    if (!el) return [];
    try {
      var data = JSON.parse(el.textContent || '[]');
      return Array.isArray(data) ? data : [];
    } catch (e) {
      return [];
    }
  }

  function formationPct(row) {
    if (row.formation_pct != null && !isNaN(row.formation_pct)) {
      return Math.max(0, Math.min(100, Math.round(Number(row.formation_pct))));
    }
    if (row.score == null || isNaN(row.score)) return null;
    return Math.max(0, Math.min(100, Math.round(Number(row.score) * 100)));
  }

  function sparkHtml(row, tone) {
    var sparks = row.spark_closes;
    if (sparks && sparks.length >= 2) {
      return (
        '<div class="pd-row__spark-wrap">' +
        '<div class="spark pd-row__spark" data-spark="' +
        esc(sparks.join(',')) +
        '" data-spark-tone="' +
        esc(tone) +
        '" role="img" aria-label="Price sparkline for ' +
        esc(row.name || 'subnet') +
        '"></div></div>'
      );
    }
    return '';
  }

  function deskRow(row, tone) {
    var pct = formationPct(row);
    var sn = row.netuid != null ? 'SN' + row.netuid : '';
    var badgeSlug = String(row.badge || '')
      .toLowerCase()
      .replace(/\s+/g, '-');
    var triad = row.triad || {};
    return (
      '<a class="pd-row pd-row--' +
      esc(tone) +
      ' pump-desk__row" href="/subnet/' +
      esc(row.netuid) +
      '" data-netuid="' +
      esc(row.netuid) +
      '">' +
      '<div class="pd-row__id">' +
      (row.badge
        ? '<span class="pd-row__badge pd-row__badge--' +
          esc(badgeSlug) +
          '">' +
          esc(row.badge) +
          '</span>'
        : '') +
      '<span class="pd-row__name">' +
      esc(row.name || sn) +
      '</span>' +
      '<span class="pd-row__sn">' +
      esc(sn) +
      '</span></div>' +
      '<div class="pd-row__stats">' +
      (pct != null
        ? '<span class="pd-row__stat"><span class="pd-row__stat-k">Flow</span> ' + pct + '</span>'
        : '') +
      (row.distance != null
        ? '<span class="pd-row__stat pd-row__stat--gap"><span class="pd-row__stat-k">Gap</span> ' +
          esc(row.distance) +
          '</span>'
        : '') +
      '<span class="pd-row__triad">' +
      '<i class="pd-dot' +
      (triad.inflow_quiet_load ? ' pd-dot--on pd-dot--in' : '') +
      '"></i>' +
      '<i class="pd-dot' +
      (triad.buy_pressure ? ' pd-dot--on pd-dot--pr' : '') +
      '"></i>' +
      '<i class="pd-dot' +
      (triad.price_coil ? ' pd-dot--on pd-dot--coil' : '') +
      '"></i></span>' +
      sparkHtml(row, tone) +
      '</div></a>'
    );
  }

  function section(title, rows, tone) {
    if (!rows.length) return '';
    return (
      '<div class="pd-board__section pump-desk__section">' +
      '<h4 class="pd-board__lbl pump-desk__section-lbl">' +
      esc(title) +
      '</h4>' +
      '<div class="pd-board__rows pump-desk__rows">' +
      rows
        .map(function (row) {
          return deskRow(row, tone);
        })
        .join('') +
      '</div></div>'
    );
  }

  function renderDesk(rows) {
    // Compact home board is owned by cockpit_hydrate (featured lead + ladder).
    if (isBoardMode()) return;
    var panel = document.getElementById('pump-desk-panel');
    if (!panel) return;
    var warming = rows.filter(function (r) {
      return r.timing === 'lead';
    });
    var active = rows.filter(function (r) {
      return r.timing === 'confirmed';
    });
    var exits = rows.filter(function (r) {
      return r.timing === 'exit';
    });
    if (!warming.length && !active.length) {
      panel.innerHTML =
        '<p class="pd-empty pump-desk__empty">Quiet — no warming or active names on the ladder right now.</p>';
      return;
    }
    panel.innerHTML =
      section('Warming', warming, 'warm') +
      section('Active', active, 'active') +
      section('Cooling', exits, 'exit');
    if (typeof window.__paintSparks === 'function') window.__paintSparks();
  }

  function highlightCard(netuid) {
    document.querySelectorAll('.pump-alert__card').forEach(function (card) {
      card.classList.toggle(
        'pump-alert__card--highlight',
        String(card.getAttribute('data-netuid')) === String(netuid)
      );
    });
    var card = document.querySelector('.pump-alert__card[data-netuid="' + netuid + '"]');
    if (card) card.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'center' });
  }

  function bindDeskClicks() {
    var panel = document.getElementById('pump-desk-panel');
    if (!panel || panel._pumpDeskBound) return;
    panel._pumpDeskBound = true;
    panel.addEventListener('click', function (ev) {
      var row = ev.target.closest('.pump-desk__row, .pd-row');
      if (!row) return;
      highlightCard(row.getAttribute('data-netuid'));
    });
  }

  function init() {
    bindDeskClicks();
    if (!isBoardMode()) renderDesk(readRows());
  }

  window.PumpMap = {
    init: init,
    refresh: function (rows) {
      var el = document.getElementById('pump-map-data');
      if (el && rows) el.textContent = JSON.stringify(rows);
      // Board mode: hydrate already painted the featured lead — only sync map JSON.
      if (isBoardMode()) return;
      renderDesk(rows || readRows());
    },
    renderDesk: renderDesk,
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
