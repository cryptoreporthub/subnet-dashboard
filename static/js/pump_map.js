(function () {
  'use strict';

  var BADGE_ABBR = {
    'WARMING UP': 'WARM',
    BUILDING: 'BUILD',
    STRONG: 'STRONG',
    'JUST STARTED': 'JUST',
    'CHASE RISK': 'CHASE',
    FADING: 'FADE',
  };

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

  function rowLabel(row) {
    if (window.SubnetNameRegistry && window.SubnetNameRegistry.resolve) {
      return window.SubnetNameRegistry.resolve(
        { name: row.name, netuid: row.netuid },
        row.netuid
      );
    }
    return row.name || (row.netuid != null ? 'SN' + row.netuid : '');
  }

  function pumpPatternLineHtml(row, classExtra) {
    if (!row || row.timing === 'exit') return '';
    var strip = row.direction_strip || row.pattern_label;
    if (!strip) return '';
    if (!row.direction_strip && row.pattern_class === 'insufficient_data') return '';
    var suffix = '';
    var prob =
      row.re_pump_prob != null && !isNaN(Number(row.re_pump_prob))
        ? Number(row.re_pump_prob)
        : null;
    if (prob != null && prob > 0) {
      suffix = ' · ' + Math.round(prob * 100) + '%';
    } else if (
      row.pattern_confidence != null &&
      !isNaN(Number(row.pattern_confidence)) &&
      Number(row.pattern_confidence) >= 0.5
    ) {
      suffix = ' · ' + Math.round(Number(row.pattern_confidence) * 100) + '%';
    }
    var title = row.pattern_class ? esc(row.pattern_class) : 'Direction path';
    var cls = 'pump-pattern-line' + (classExtra ? ' ' + classExtra : '');
    return (
      '<div class="pump-pattern-rail"><p class="' +
      cls +
      '" title="' +
      title +
      '">' +
      esc(strip) +
      suffix +
      '</p></div>'
    );
  }

  function deskRow(row, tone) {
    var pct = formationPct(row);
    var sn = row.netuid != null ? 'SN' + row.netuid : '';
    var badge = String(row.badge || '');
    var badgeSlug = badge.toLowerCase().replace(/\s+/g, '-');
    var shortBadge = BADGE_ABBR[badge] || badge;
    var labels = row.triad_labels || {};
    var triad = row.triad || {};
    var why = row.trigger || row.subtitle || row.badge || '';
    if (why.length > 72) why = why.slice(0, 69).replace(/\s+\S*$/, '') + '…';
    return (
      '<a class="pd-r pd-r--' +
      esc(tone) +
      ' pump-desk__row" href="/subnet/' +
      esc(row.netuid) +
      '" data-netuid="' +
      esc(row.netuid) +
      '" title="' +
      esc(badge) +
      '">' +
      '<div class="pd-r__top"><div class="pd-r__id">' +
      '<span class="pd-r__badge pd-r__badge--' +
      esc(badgeSlug) +
      '">' +
      esc(shortBadge) +
      '</span>' +
      '<span class="pd-r__name">' +
      esc(rowLabel(row)) +
      ' <b class="pd-r__sn">' +
      esc(sn) +
      '</b></span></div>' +
      '<div class="pd-r__nums"><span class="pd-r__num"><i>Flow</i> ' +
      (pct != null ? pct : '—') +
      '</span><span class="pd-r__num pd-r__num--gap"><i>Gap</i> ' +
      (row.distance != null ? esc(row.distance) : '—') +
      '</span></div></div>' +
      pumpPatternLineHtml(row) +
      (why ? '<p class="pd-r__why">' + esc(why) + '</p>' : '') +
      '<span class="pd-r__legs">' +
      '<span class="pd-r__leg' +
      (triad.inflow_quiet_load ? ' pd-r__leg--on' : '') +
      '">In ' +
      esc(labels.inflow || 'WATCH') +
      '</span>' +
      '<span class="pd-r__leg' +
      (triad.buy_pressure ? ' pd-r__leg--on' : '') +
      '">Pr ' +
      esc(labels.pressure || 'FLAT') +
      '</span>' +
      '<span class="pd-r__leg' +
      (triad.price_coil ? ' pd-r__leg--on' : '') +
      '">Coil ' +
      esc(labels.coil || 'OPEN') +
      '</span></span></a>'
    );
  }

  function section(title, rows, tone) {
    if (!rows.length) return '';
    return (
      '<h4 class="pd-board__lbl">' +
      esc(title) +
      '</h4><div class="pd-board__rows">' +
      rows
        .map(function (row) {
          return deskRow(row, tone);
        })
        .join('') +
      '</div>'
    );
  }

  function renderDesk(rows) {
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
      section('Warming', warming, 'warm') + section('Active', active, 'active') + section('Cooling', exits, 'exit');
  }

  function highlightCard(netuid) {
    document.querySelectorAll('.pump-alert__card').forEach(function (card) {
      card.classList.toggle(
        'pump-alert__card--highlight',
        String(card.getAttribute('data-netuid')) === String(netuid)
      );
    });
  }

  function bindDeskClicks() {
    var panel = document.getElementById('pump-desk-panel');
    if (!panel || panel._pumpDeskBound) return;
    panel._pumpDeskBound = true;
    panel.addEventListener('click', function (ev) {
      var row = ev.target.closest('.pump-desk__row, .pd-r');
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
