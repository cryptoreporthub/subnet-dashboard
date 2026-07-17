/** §28-3 — global command palette (Cmd/Ctrl+K) */
(function () {
  'use strict';

  var palette = null;
  var input = null;
  var list = null;
  var activeIdx = 0;
  var results = [];
  var debounce = null;

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c];
    });
  }

  function ensurePalette() {
    if (palette) return palette;
    palette = document.createElement('div');
    palette.id = 'cmd-palette';
    palette.className = 'cmd-palette';
    palette.hidden = true;
    palette.innerHTML =
      '<div class="cmd-palette__backdrop" data-close="1"></div>' +
      '<div class="cmd-palette__panel" role="dialog" aria-modal="true" aria-label="Search">' +
      '<input type="search" class="cmd-palette__input" id="cmd-palette-input" role="combobox" aria-expanded="false" aria-controls="cmd-palette-list" aria-autocomplete="list" placeholder="Subnet, wallet, or pick id…" autocomplete="off" />' +
      '<ul class="cmd-palette__list" id="cmd-palette-list" role="listbox"></ul>' +
      '</div>';
    document.body.appendChild(palette);
    input = document.getElementById('cmd-palette-input');
    list = document.getElementById('cmd-palette-list');
    palette.addEventListener('click', function (e) {
      if (e.target.closest('[data-close]')) close();
    });
    input.addEventListener('input', function () {
      clearTimeout(debounce);
      debounce = setTimeout(function () { search(input.value); }, 180);
    });
    input.addEventListener('keydown', onKeydown);
    list.addEventListener('click', function (e) {
      var item = e.target.closest('.cmd-palette__item');
      if (item) go(item.getAttribute('data-url'));
    });
    return palette;
  }

  function render() {
    if (!list) return;
    if (!results.length) {
      list.innerHTML = '<li class="cmd-palette__item" style="cursor:default;color:#8a9a8e;">No matches</li>';
      return;
    }
    list.innerHTML = results.map(function (r, i) {
      var active = i === activeIdx;
      return '<li class="cmd-palette__item' + (active ? ' cmd-palette__item--active' : '') + '" id="cmd-palette-opt-' + i + '" data-url="' + esc(r.url) + '" role="option" aria-selected="' + (active ? 'true' : 'false') + '">' +
        '<span>' + esc(r.label) + '</span>' +
        '<span class="cmd-palette__hint">' + esc(r.hint || r.type) + '</span></li>';
    }).join('');
    if (input) {
      input.setAttribute('aria-activedescendant', results.length ? 'cmd-palette-opt-' + activeIdx : '');
    }
  }

  function search(q) {
    if (!q || q.length < 1) {
      results = [];
      render();
      return;
    }
    fetch('/api/search?q=' + encodeURIComponent(q) + '&limit=8')
      .then(function (r) { return r.json(); })
      .then(function (d) {
        results = d.results || [];
        activeIdx = 0;
        render();
      })
      .catch(function () {
        results = [];
        render();
      });
  }

  function go(url) {
    if (!url) return;
    window.location.href = url;
  }

  function onKeydown(e) {
    if (e.key === 'Escape') {
      e.preventDefault();
      close();
      return;
    }
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      activeIdx = Math.min(activeIdx + 1, Math.max(0, results.length - 1));
      render();
      return;
    }
    if (e.key === 'ArrowUp') {
      e.preventDefault();
      activeIdx = Math.max(activeIdx - 1, 0);
      render();
      return;
    }
    if (e.key === 'Enter' && results[activeIdx]) {
      e.preventDefault();
      go(results[activeIdx].url);
    }
  }

  function open() {
    ensurePalette();
    palette.hidden = false;
    if (input) input.setAttribute('aria-expanded', 'true');
    input.value = '';
    results = [];
    render();
    setTimeout(function () { input.focus(); }, 0);
  }

  function close() {
    if (palette) palette.hidden = true;
    if (input) {
      input.setAttribute('aria-expanded', 'false');
      input.removeAttribute('aria-activedescendant');
    }
  }

  document.addEventListener('keydown', function (e) {
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
      e.preventDefault();
      open();
    }
  });

  document.addEventListener('DOMContentLoaded', function () {
    var btn = document.getElementById('cmd-palette-trigger');
    if (btn) btn.addEventListener('click', open);
  });

  window.SimiSearch = { open: open, close: close };
})();
