(function () {
  'use strict';

  var reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var MOBILE_MAX = 720;

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

  function yForRow(row) {
    if (row.price_change_1h != null && !isNaN(row.price_change_1h)) return Number(row.price_change_1h);
    if (row.price_change_24h != null && !isNaN(row.price_change_24h)) return Number(row.price_change_24h);
    if (row.timing === 'lead') return 0.35;
    if (row.timing === 'confirmed') return 0.7;
    if (row.timing === 'exit') return 0.5;
    return 0;
  }

  function xForRow(row) {
    var triad = row.triad || {};
    var lit = 0;
    if (triad.inflow_quiet_load) lit++;
    if (triad.buy_pressure) lit++;
    if (triad.price_coil) lit++;
    if (lit > 0) return lit / 3;
    if (row.score != null && !isNaN(row.score)) return Math.max(0, Math.min(1, Number(row.score)));
    return 0.25;
  }

  function zoneLabel(x, y) {
    if (x >= 0.55 && y < 0.15) return 'Coiled';
    if (x >= 0.55 && y >= 0.15) return 'Breakout';
    if (x < 0.55 && y >= 0.15) return 'Early';
    return 'Fading';
  }

  function dotColor(timing) {
    if (timing === 'lead') return '#7dd3fc';
    if (timing === 'confirmed') return '#fbbf24';
    return '#94a3b8';
  }

  function setView(mode) {
    var mapPanel = document.getElementById('pump-map-panel');
    var listPanel = document.getElementById('pump-list-panel');
    var toggles = document.querySelectorAll('[data-pump-view]');
    toggles.forEach(function (btn) {
      var on = btn.getAttribute('data-pump-view') === mode;
      btn.classList.toggle('is-active', on);
      btn.setAttribute('aria-selected', on ? 'true' : 'false');
    });
    if (mapPanel) mapPanel.hidden = mode !== 'chart';
    if (listPanel) listPanel.hidden = mode !== 'list';
  }

  function highlightCard(netuid) {
    document.querySelectorAll('.pump-alert__card').forEach(function (card) {
      card.classList.toggle('pump-alert__card--highlight', String(card.getAttribute('data-netuid')) === String(netuid));
    });
    var card = document.querySelector('.pump-alert__card[data-netuid="' + netuid + '"]');
    if (card) card.scrollIntoView({ behavior: reduceMotion ? 'auto' : 'smooth', block: 'nearest', inline: 'center' });
  }

  function draw() {
    var canvas = document.getElementById('pump-map-canvas');
    if (!canvas) return;
    var rows = readRows();
    var dpr = window.devicePixelRatio || 1;
    var rect = canvas.getBoundingClientRect();
    var w = Math.max(280, rect.width || canvas.clientWidth || 320);
    var h = Math.max(180, rect.height || canvas.clientHeight || 220);
    canvas.width = w * dpr;
    canvas.height = h * dpr;
    var ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);

    var pad = { l: 36, r: 12, t: 20, b: 28 };
    var plotW = w - pad.l - pad.r;
    var plotH = h - pad.t - pad.b;

    ctx.fillStyle = '#0a0c10';
    ctx.fillRect(0, 0, w, h);

    ctx.strokeStyle = 'rgba(148, 163, 184, 0.15)';
    ctx.lineWidth = 1;
    ctx.strokeRect(pad.l, pad.t, plotW, plotH);
    ctx.setLineDash([4, 4]);
    ctx.beginPath();
    ctx.moveTo(pad.l + plotW * 0.55, pad.t);
    ctx.lineTo(pad.l + plotW * 0.55, pad.t + plotH);
    ctx.moveTo(pad.l, pad.t + plotH * 0.45);
    ctx.lineTo(pad.l + plotW, pad.t + plotH * 0.45);
    ctx.stroke();
    ctx.setLineDash([]);

    var zones = [
      { x: 0.12, y: 0.18, t: 'Fading', c: 'rgba(148,163,184,0.55)' },
      { x: 0.78, y: 0.18, t: 'Coiled', c: 'rgba(125,211,252,0.65)' },
      { x: 0.12, y: 0.78, t: 'Early', c: 'rgba(52,211,153,0.6)' },
      { x: 0.78, y: 0.78, t: 'Breakout', c: 'rgba(251,191,36,0.6)' },
    ];
    ctx.font = '10px JetBrains Mono, monospace';
    zones.forEach(function (z) {
      ctx.fillStyle = z.c;
      ctx.fillText(z.t, pad.l + plotW * z.x, pad.t + plotH * z.y);
    });

    ctx.fillStyle = '#64748b';
    ctx.fillText('Formation →', pad.l, h - 8);
    ctx.save();
    ctx.translate(10, pad.t + plotH / 2);
    ctx.rotate(-Math.PI / 2);
    ctx.fillText('Momentum ↑', 0, 0);
    ctx.restore();

    if (!rows.length) {
      ctx.fillStyle = '#64748b';
      ctx.fillText('Quiet — no dots to plot', pad.l + 12, pad.t + plotH / 2);
      canvas._pumpMapHits = [];
      return;
    }

    var hits = [];
    rows.forEach(function (row, idx) {
      var x = xForRow(row);
      var yRaw = yForRow(row);
      var y = Math.max(-5, Math.min(15, yRaw));
      var yNorm = (y + 2) / 12;
      var px = pad.l + x * plotW;
      var py = pad.t + plotH - yNorm * plotH;
      hits.push({ x: px, y: py, r: 10, row: row, idx: idx });
      ctx.beginPath();
      ctx.fillStyle = dotColor(row.timing);
      ctx.arc(px, py, 6, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = '#e2e8f0';
      ctx.font = '9px Rajdhani, sans-serif';
      ctx.fillText(String(row.name || '').slice(0, 10), px + 8, py + 3);
    });
    canvas._pumpMapHits = hits;
  }

  function onCanvasClick(ev) {
    var canvas = document.getElementById('pump-map-canvas');
    if (!canvas || !canvas._pumpMapHits) return;
    var rect = canvas.getBoundingClientRect();
    var x = ev.clientX - rect.left;
    var y = ev.clientY - rect.top;
    for (var i = 0; i < canvas._pumpMapHits.length; i++) {
      var hit = canvas._pumpMapHits[i];
      var dx = x - hit.x;
      var dy = y - hit.y;
      if (dx * dx + dy * dy <= hit.r * hit.r) {
        setView('list');
        highlightCard(hit.row.netuid);
        return;
      }
    }
  }

  function bindToggles() {
    document.querySelectorAll('[data-pump-view]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        setView(btn.getAttribute('data-pump-view') || 'chart');
      });
    });
  }

  function defaultView() {
    setView(window.innerWidth <= MOBILE_MAX ? 'chart' : 'list');
  }

  function init() {
    bindToggles();
    defaultView();
    draw();
    var canvas = document.getElementById('pump-map-canvas');
    if (canvas) canvas.addEventListener('click', onCanvasClick);
    window.addEventListener('resize', draw);
  }

  window.PumpMap = {
    init: init,
    refresh: function (rows) {
      var el = document.getElementById('pump-map-data');
      if (el && rows) el.textContent = JSON.stringify(rows);
      draw();
    },
    setView: setView,
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
