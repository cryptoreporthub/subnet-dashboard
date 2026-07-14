/* SimiVision Cockpit — minimal vanilla JS controller */
(function () {
  'use strict';

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c];
    });
  }

  // ---------- UTC clock ----------
  function updateClock() {
    var el = document.getElementById('utcClock');
    if (!el) return;
    var now = new Date();
    el.textContent = now.toISOString().split('T')[1].split('.')[0] + ' UTC';
  }
  updateClock();
  setInterval(updateClock, 1000);

  // ---------- Tab controller ----------
  var tabBar = document.querySelector('.tab-bar');
  if (tabBar) {
    tabBar.addEventListener('click', function (e) {
      var btn = e.target.closest('.tab-btn');
      if (!btn) return;

      var targetId = 'panel-' + btn.dataset.tab;
      var panels = document.querySelectorAll('.tab-panel');
      var buttons = tabBar.querySelectorAll('.tab-btn');

      buttons.forEach(function (b) {
        var active = b === btn;
        b.classList.toggle('active', active);
        b.setAttribute('aria-selected', active ? 'true' : 'false');
      });

      panels.forEach(function (p) {
        p.classList.toggle('active', p.id === targetId);
      });
    });
  }

  // ---------- Compact/expand toggle ----------
  function toggleCompact() {
    document.body.classList.toggle('compact');
  }

  document.addEventListener('keydown', function (e) {
    if (e.key === 'c' && !['INPUT', 'TEXTAREA'].includes(e.target.tagName)) {
      toggleCompact();
    }
  });

  // ---------- Sparklines (uPlot — see uplot_charts.js) ----------
  window.__paintSparks = window.__paintSparks || function () {};

  // ---------- Radar chart (Chart.js lazy-loaded when data-radar present) ----------
  var chartJsPromise = null;

  function loadChartJs() {
    if (typeof Chart !== 'undefined') return Promise.resolve();
    if (!chartJsPromise) {
      chartJsPromise = new Promise(function (resolve, reject) {
        var s = document.createElement('script');
        s.src = 'https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js';
        s.onload = resolve;
        s.onerror = reject;
        document.head.appendChild(s);
      });
    }
    return chartJsPromise;
  }

  function destroyChart(canvas) {
    if (typeof Chart === 'undefined' || !canvas) return;
    var existing = Chart.getChart(canvas);
    if (existing) existing.destroy();
  }

  function hexToRgba(hex, a) {
    var h = (hex || '').replace('#', '');
    if (h.length === 3) { h = h.split('').map(function (c) { return c + c; }).join(''); }
    var n = parseInt(h, 16);
    if (isNaN(n)) return 'rgba(16,185,129,' + a + ')';
    var r = (n >> 16) & 255, g = (n >> 8) & 255, b = n & 255;
    return 'rgba(' + r + ',' + g + ',' + b + ',' + a + ')';
  }

  function drawRadar() {
    var radarCanvas = document.getElementById('radarChart');
    if (!radarCanvas || typeof Chart === 'undefined') return;
    var raw = radarCanvas.getAttribute('data-radar');
    if (!raw) return;
    try {
      var radarData = JSON.parse(raw);
      if (!radarData.labels || !radarData.datasets) return;
      destroyChart(radarCanvas);
      new Chart(radarCanvas.getContext('2d'), {
        type: 'radar',
        data: {
          labels: radarData.labels,
          datasets: radarData.datasets.map(function (ds) {
            return {
              label: ds.label,
              data: ds.data,
              borderColor: ds.color || '#34d399',
              backgroundColor: hexToRgba(ds.color || '#34d399', 0.18),
              borderWidth: 2,
              pointRadius: 2,
              pointBackgroundColor: ds.color || '#34d399'
            };
          })
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: {
              labels: { color: '#8cb39f', font: { family: 'JetBrains Mono', size: 11 } }
            }
          },
          scales: {
            r: {
              angleLines: { color: 'rgba(233,247,239,0.06)' },
              grid: { color: 'rgba(233,247,239,0.06)' },
              pointLabels: { color: '#8cb39f', font: { family: 'JetBrains Mono', size: 11 } },
              ticks: { display: false, backdropColor: 'transparent' },
              suggestedMin: 0,
              suggestedMax: 100
            }
          }
        }
      });
    } catch (e) { console.error('Radar chart error', e); }
  }

  function paintRadar() {
    var radarCanvas = document.getElementById('radarChart');
    if (!radarCanvas) return;
    if (!radarCanvas.getAttribute('data-radar')) return;
    loadChartJs().then(drawRadar).catch(function (e) {
      console.error('Chart.js load failed', e);
    });
  }

  window.__paintRadar = paintRadar;
  window.__paintSparks();
  paintRadar();

  // ---------- Chat ----------
  (function () {
    var log = document.getElementById('chatLog');
    var input = document.getElementById('chatInput');
    var btn = document.getElementById('chatSend');
    var meta = document.getElementById('chatMeta');
    if (!log || !input || !btn) return;

    function add(text, who) {
      var d = document.createElement('div');
      d.className = 'chat-msg ' + (who === 'user' ? 'user' : 'bot');
      d.innerHTML = '<div class="who">' + (who === 'user' ? 'YOU' : 'SIMIVISION') + '</div>' + esc(text).replace(/\n/g, '<br>');
      log.appendChild(d);
      log.scrollTop = log.scrollHeight;
    }

    function send() {
      var msg = (input.value || '').trim();
      if (!msg) return;
      add(msg, 'user');
      input.value = '';
      btn.disabled = true;
      if (meta) meta.textContent = 'LLM: thinking…';
      fetch('/api/simivision/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: msg })
      })
        .then(function (r) { return r.json(); })
        .then(function (j) {
          var d = (j && j.data) || {};
          add((d.reply || 'No response.').replace(/\n/g, '\n'), 'bot');
          if (meta) meta.textContent = 'LLM: ' + (d.llm_used ? 'used' : 'local fallback') + ' · records ' + ((d.mindmap_context || {}).learning_records || 0);
        })
        .catch(function () {
          add('Connection error — intelligence layer unreachable.', 'bot');
          if (meta) meta.textContent = 'LLM: error';
        })
        .finally(function () { btn.disabled = false; input.focus(); });
    }

    btn.addEventListener('click', send);
    input.addEventListener('keydown', function (e) { if (e.key === 'Enter') send(); });
  })();
})();
