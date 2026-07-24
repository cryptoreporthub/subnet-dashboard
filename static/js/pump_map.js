(function () {
  'use strict';

  function esc(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c];
    });
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
    if (row.score == null || isNaN(row.score)) return null;
    return Math.max(0, Math.min(100, Math.round(Number(row.score) * 100)));
  }

  function sparkHtml(row, tone) {
    var sparks = row.spark_closes;
    if (sparks && sparks.length >= 2) {
      return (
        '<div class="pump-desk__spark-wrap">' +
        '<div class="spark pump-desk__spark" data-spark="' +
        esc(sparks.join(',')) +
        '" data-spark-tone="' +
        esc(tone) +
        '" role="img" aria-label="Price sparkline for ' +
        esc(row.name || 'subnet') +
        '"></div></div>'
      );
    }
    return '<div class="pump-desk__spark-empty" aria-hidden="true">—</div>';
  }

  function deskRow(row, tone) {
    var pct = formationPct(row);
    var sn = row.netuid != null ? 'SN' + row.netuid : '';
    return (
      '<a class="pump-desk__row pump-desk__row--' +
      esc(tone) +
      '" href="/subnet/' +
      esc(row.netuid) +
      '" data-netuid="' +
      esc(row.netuid) +
      '">' +
      '<div class="pump-desk__row-main">' +
      '<span class="pump-desk__name">' +
      esc(row.name || sn) +
      '</span>' +
      '<span class="pump-desk__sn">' +
      esc(sn) +
      '</span>' +
      '</div>' +
      '<div class="pump-desk__row-meta">' +
      (pct != null
        ? '<span class="pump-desk__formation"><span class="pump-desk__formation-lbl">Formation</span> ' +
          pct +
          '%</span>'
        : '') +
      sparkHtml(row, tone) +
      '</div></a>'
    );
  }

  function section(title, rows, tone) {
    if (!rows.length) return '';
    return (
      '<div class="pump-desk__section">' +
      '<p class="pump-desk__section-lbl">' +
      esc(title) +
      '</p>' +
      '<div class="pump-desk__rows">' +
      rows.map(function (row) {
        return deskRow(row, tone);
      }).join('') +
      '</div></div>'
    );
  }

  function renderDesk(rows) {
    var panel = document.getElementById('pump-desk-panel');
    if (!panel) return;
    var warming = rows.filter(function (r) {
      return r.timing === 'lead';
    });
    var active = rows.filter(function (r) {
      return r.timing === 'confirmed';
    });
    if (!warming.length && !active.length) {
      panel.innerHTML =
        '<p class="pump-desk__empty">Quiet — no warming or active names on the ladder right now.</p>';
      return;
    }
    panel.innerHTML = section('Warming', warming, 'warm') + section('Active', active, 'active');
    if (typeof window.__paintSparks === 'function') window.__paintSparks();
  }

  function highlightCard(netuid) {
    document.querySelectorAll('.pump-alert__card').forEach(function (card) {
      card.classList.toggle('pump-alert__card--highlight', String(card.getAttribute('data-netuid')) === String(netuid));
    });
    var card = document.querySelector('.pump-alert__card[data-netuid="' + netuid + '"]');
    if (card) card.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'center' });
  }

  function bindDeskClicks() {
    var panel = document.getElementById('pump-desk-panel');
    if (!panel || panel._pumpDeskBound) return;
    panel._pumpDeskBound = true;
    panel.addEventListener('click', function (ev) {
      var row = ev.target.closest('.pump-desk__row');
      if (!row) return;
      highlightCard(row.getAttribute('data-netuid'));
    });
  }

  function init() {
    bindDeskClicks();
    renderDesk(readRows());
  }

  window.PumpMap = {
    init: init,
    refresh: function (rows) {
      var el = document.getElementById('pump-map-data');
      if (el && rows) el.textContent = JSON.stringify(rows);
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
