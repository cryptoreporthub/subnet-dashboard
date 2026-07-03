/* SimiVision Cockpit — minimal vanilla JS controller */
(function () {
  'use strict';

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

  // ---------- Sparklines (Chart.js mini line) ----------
  function drawSpark(canvas) {
    var raw = canvas.getAttribute('data-spark');
    if (!raw) return;
    var pts = raw.split(',').map(Number).filter(function (n) { return !isNaN(n); });
    if (pts.length < 2) return;
    var up = pts[pts.length - 1] >= pts[0];
    var col = up ? '#00ff41' : '#ff3366';
    var ctx = canvas.getContext('2d');
    var grad = ctx.createLinearGradient(0, 0, 0, canvas.height || 36);
    grad.addColorStop(0, up ? 'rgba(0, 255, 65, 0.25)' : 'rgba(255, 51, 102, 0.25)');
    grad.addColorStop(1, up ? 'rgba(0, 255, 65, 0.0)' : 'rgba(255, 51, 102, 0.0)');

    new Chart(ctx, {
      type: 'line',
      data: {
        labels: pts.map(function (_, i) { return i; }),
        datasets: [{
          data: pts,
          borderColor: col,
          backgroundColor: grad,
          fill: true,
          tension: 0.4,
          pointRadius: 0,
          borderWidth: 1.6
        }]
      },
      options: {
        responsive: false,
        maintainAspectRatio: false,
        animation: false,
        plugins: { legend: { display: false }, tooltip: { enabled: false } },
        scales: { x: { display: false }, y: { display: false } },
        elements: { line: { borderCapStyle: 'round', borderJoinStyle: 'round' } }
      }
    });
  }

  document.querySelectorAll('canvas.spark').forEach(drawSpark);

  // ---------- Radar chart (optional momentum context) ----------
  function hexToRgba(hex, a) {
    var h = (hex || '').replace('#', '');
    if (h.length === 3) { h = h.split('').map(function (c) { return c + c; }).join(''); }
    var n = parseInt(h, 16);
    if (isNaN(n)) return 'rgba(16,185,129,' + a + ')';
    var r = (n >> 16) & 255, g = (n >> 8) & 255, b = n & 255;
    return 'rgba(' + r + ',' + g + ',' + b + ',' + a + ')';
  }

  (function () {
    var radarCanvas = document.getElementById('radarChart');
    if (!radarCanvas) return;
    var raw = radarCanvas.getAttribute('data-radar');
    if (!raw) return;
    try {
      var radarData = JSON.parse(raw);
      if (!radarData.labels || !radarData.datasets) return;
      new Chart(radarCanvas.getContext('2d'), {
        type: 'radar',
        data: {
          labels: radarData.labels,
          datasets: radarData.datasets.map(function (ds) {
            return {
              label: ds.label,
              data: ds.data,
              borderColor: ds.color || '#00ff41',
              backgroundColor: hexToRgba(ds.color || '#00ff41', 0.18),
              borderWidth: 2,
              pointRadius: 2,
              pointBackgroundColor: ds.color || '#00ff41'
            };
          })
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: {
              labels: { color: '#00f0ff', font: { family: 'JetBrains Mono', size: 11 } }
            }
          },
          scales: {
            r: {
              angleLines: { color: 'rgba(240, 246, 252, 0.06)' },
              grid: { color: 'rgba(240, 246, 252, 0.06)' },
              pointLabels: { color: '#00f0ff', font: { family: 'JetBrains Mono', size: 11 } },
              ticks: { display: false, backdropColor: 'transparent' },
              suggestedMin: 0,
              suggestedMax: 100
            }
          }
        }
      });
    } catch (e) { console.error('Radar chart error', e); }
  })();

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
      d.innerHTML = '<div class="who">' + (who === 'user' ? 'YOU' : 'SIMIVISION') + '</div>' + text;
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
          add((d.reply || 'No response.').replace(/\n/g, '<br>'), 'bot');
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
