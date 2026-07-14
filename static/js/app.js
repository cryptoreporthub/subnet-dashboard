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

  // ---------- Chart paint hooks (uplot_charts.js defines __paintSparks / __paintRadar) ----------
  if (typeof window.__paintSparks === 'function') window.__paintSparks();
  if (typeof window.__paintRadar === 'function') window.__paintRadar();

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
