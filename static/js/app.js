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

  // ---------- Chart paint hooks (uplot_charts.js defines __paintSparks / __paintRadar) ----------
  if (typeof window.__paintSparks === 'function') window.__paintSparks();
  if (typeof window.__paintRadar === 'function') window.__paintRadar();
})();
