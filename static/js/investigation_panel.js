/* On-chain investigation + whale leaderboards UI */
(function () {
  'use strict';

  var sellersBtn = document.getElementById('inv-sellers-btn');
  var walletBtn = document.getElementById('inv-wallet-btn');
  var boardsEl = document.getElementById('whale-leaderboards');
  if (!sellersBtn && !boardsEl) return;

  function esc(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c];
    });
  }

  function fmtOut(data) {
    try {
      return JSON.stringify(data, null, 2);
    } catch (e) {
      return String(data);
    }
  }

  if (sellersBtn) {
    sellersBtn.addEventListener('click', function () {
      var netuid = document.getElementById('inv-netuid').value || '82';
      var out = document.getElementById('inv-sellers-out');
      out.textContent = 'Loading…';
      fetch('/api/investigate/subnet/' + encodeURIComponent(netuid) + '/sellers?limit=25')
        .then(function (r) { return r.json(); })
        .then(function (d) { out.textContent = fmtOut(d); })
        .catch(function () { out.textContent = 'Investigation API unavailable.'; });
    });
  }

  if (walletBtn) {
    walletBtn.addEventListener('click', function () {
      var wallet = (document.getElementById('inv-wallet').value || '').trim();
      var out = document.getElementById('inv-wallet-out');
      if (!wallet) {
        out.textContent = 'Enter a coldkey SS58 address.';
        return;
      }
      out.textContent = 'Loading…';
      fetch('/api/investigate/wallet/' + encodeURIComponent(wallet) + '?limit=30')
        .then(function (r) { return r.json(); })
        .then(function (d) { out.textContent = fmtOut(d); })
        .catch(function () { out.textContent = 'Investigation API unavailable.'; });
    });
  }

  if (boardsEl) {
    fetch('/api/whales/leaderboards?limit=8')
      .then(function (r) { return r.json(); })
      .then(function (payload) {
        var boards = payload.leaderboards || {};
        var keys = Object.keys(boards);
        if (!keys.length) {
          boardsEl.innerHTML = '<p class="empty">No whale data yet — run a scan or set TAOSTATS_API_KEY.</p>';
          return;
        }
        boardsEl.innerHTML = keys.map(function (cat) {
          var rows = boards[cat] || [];
          var lis = rows.slice(0, 5).map(function (row) {
            var w = row.wallet || row.ss58 || '—';
            return '<li><code>' + esc(w.slice(0, 10)) + '…</code> · ' + esc(row.score != null ? row.score : '') + '</li>';
          }).join('');
          return '<div class="whale-board"><h4>' + esc(cat) + '</h4><ul>' + lis + '</ul></div>';
        }).join('');
      })
      .catch(function () {
        boardsEl.innerHTML = '<p class="empty">Whale leaderboards unavailable.</p>';
      });
  }
})();
