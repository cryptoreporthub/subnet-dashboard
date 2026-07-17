/* §27-3b — On-chain investigation: tables + focus-coupled presets */
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

  function focusNetuid() {
    if (window.LivingFocus && window.LivingFocus.netuid != null) {
      return window.LivingFocus.netuid;
    }
    var root = document.getElementById('section-living-focus');
    if (root && root.getAttribute('data-focus-netuid')) {
      return root.getAttribute('data-focus-netuid');
    }
    var inp = document.getElementById('inv-netuid');
    return (inp && inp.value) || '82';
  }

  function focusName() {
    if (window.LivingFocus && window.LivingFocus.name) return window.LivingFocus.name;
    return 'SN' + focusNetuid();
  }

  function txLink(hash) {
    if (!hash) return '—';
    var url = 'https://taostats.io/hash/' + encodeURIComponent(hash);
    return '<a href="' + esc(url) + '" target="_blank" rel="noopener">' + esc(String(hash).slice(0, 10)) + '…</a>';
  }

  function renderSellersTable(payload, out) {
    if (!out) return;
    if (payload.error || payload.status === 'error') {
      out.innerHTML = '<p class="inv-banner">' + esc(payload.error || payload.message || 'Investigation API unavailable.') + '</p>';
      return;
    }
    var rows = payload.sellers || payload.rows || payload.data || [];
    if (!rows.length) {
      out.innerHTML = '<p class="inv-empty">No sellers returned — TaoStats may be unavailable.</p>';
      return;
    }
    var html = '<table class="inv-table"><thead><tr><th>Wallet</th><th>Side</th><th>TAO</th><th>Time</th><th>Tx</th></tr></thead><tbody>';
    rows.slice(0, 25).forEach(function (row) {
      var wallet = row.wallet || row.ss58 || row.coldkey || '—';
      var walletCell = wallet !== '—'
        ? '<a href="/wallet/' + encodeURIComponent(wallet) + '"><code>' + esc(String(wallet).slice(0, 12)) + '…</code></a>'
        : '—';
      html += '<tr><td>' + walletCell + '</td>' +
        '<td>' + esc(row.side || row.type || '—') + '</td>' +
        '<td>' + esc(row.amount != null ? row.amount : row.tao != null ? row.tao : '—') + '</td>' +
        '<td>' + esc(row.time || row.timestamp || '—') + '</td>' +
        '<td>' + txLink(row.tx_hash || row.hash || row.extrinsic_hash) + '</td></tr>';
    });
    html += '</tbody></table>';
    out.innerHTML = html;
  }

  function renderWalletTable(payload, out) {
    if (!out) return;
    if (payload.error || payload.status === 'error') {
      out.innerHTML = '<p class="inv-banner">' + esc(payload.error || payload.message || 'Wallet trace unavailable.') + '</p>';
      return;
    }
    var rows = payload.flow || payload.transfers || payload.rows || [];
    if (!rows.length) {
      out.innerHTML = '<p class="inv-empty">No wallet flow rows.</p>';
      return;
    }
    var html = '<table class="inv-table"><thead><tr><th>Dir</th><th>Amount</th><th>Subnet</th><th>Time</th><th>Tx</th></tr></thead><tbody>';
    rows.slice(0, 30).forEach(function (row) {
      html += '<tr><td>' + esc(row.direction || row.side || '—') + '</td>' +
        '<td>' + esc(row.amount != null ? row.amount : '—') + '</td>' +
        '<td>' + esc(row.netuid != null ? 'SN' + row.netuid : row.subnet || '—') + '</td>' +
        '<td>' + esc(row.time || row.timestamp || '—') + '</td>' +
        '<td>' + txLink(row.tx_hash || row.hash) + '</td></tr>';
    });
    html += '</tbody></table>';
    out.innerHTML = html;
  }

  function runSellers(netuid) {
    var out = document.getElementById('inv-sellers-out');
    var n = netuid != null ? netuid : focusNetuid();
    var inp = document.getElementById('inv-netuid');
    if (inp) inp.value = String(n);
    if (out) out.innerHTML = '<p class="inv-loading">Loading sellers…</p>';
    return fetch('/api/investigate/subnet/' + encodeURIComponent(n) + '/sellers?limit=25')
      .then(function (r) { return r.json(); })
      .then(function (d) { renderSellersTable(d, out); })
      .catch(function () {
        if (out) out.innerHTML = '<p class="inv-banner">Investigation API unavailable.</p>';
      });
  }

  if (sellersBtn) {
    sellersBtn.addEventListener('click', function () { runSellers(); });
  }

  if (walletBtn) {
    walletBtn.addEventListener('click', function () {
      var wallet = (document.getElementById('inv-wallet').value || '').trim();
      var out = document.getElementById('inv-wallet-out');
      if (!wallet) {
        if (out) out.innerHTML = '<p class="inv-empty">Enter a coldkey SS58 address.</p>';
        return;
      }
      if (out) out.innerHTML = '<p class="inv-loading">Loading…</p>';
      fetch('/api/investigate/wallet/' + encodeURIComponent(wallet) + '/flow?limit=30')
        .then(function (r) { return r.json(); })
        .then(function (d) { renderWalletTable(d, out); })
        .catch(function () {
          if (out) out.innerHTML = '<p class="inv-banner">Investigation API unavailable.</p>';
        });
    });
  }

  function renderAskResult(payload, out) {
    if (!out) return;
    if (payload.error || payload.status === 'error') {
      out.innerHTML = '<p class="inv-banner">' + esc(payload.error || payload.message || 'Ask API unavailable.') + '</p>';
      return;
    }
    var answer = payload.answer || payload.summary || payload.report || payload.markdown;
    if (!answer && payload.sections) {
      answer = JSON.stringify(payload.sections, null, 2);
    }
    out.innerHTML = '<div class="inv-ask-result"><pre>' + esc(answer || 'No answer returned.') + '</pre></div>';
  }

  function runOwnerCheck(netuid) {
    var out = document.getElementById('inv-sellers-out');
    var n = netuid != null ? netuid : focusNetuid();
    if (out) out.innerHTML = '<p class="inv-loading">Running owner check…</p>';
    return fetch('/api/investigate/subnet/' + encodeURIComponent(n) + '/sellers?limit=10')
      .then(function (r) { return r.json(); })
      .then(function (sellersPayload) {
        var rows = sellersPayload.sellers || sellersPayload.rows || sellersPayload.data || [];
        var wallets = rows.slice(0, 5).map(function (row) {
          return row.wallet || row.ss58 || row.coldkey;
        }).filter(Boolean);
        if (!wallets.length) {
          if (out) out.innerHTML = '<p class="inv-empty">No seller wallets to check.</p>';
          return;
        }
        var q = '/api/investigate/subnet/' + encodeURIComponent(n) + '/owner-check?wallets=' +
          encodeURIComponent(wallets.join(','));
        return fetch(q).then(function (r) { return r.json(); }).then(function (d) {
          if (!out) return;
          var matches = d.matches || d.results || d.owners || [];
          if (Array.isArray(matches) && matches.length) {
            out.innerHTML = '<p class="inv-banner">Owner overlap: ' + esc(JSON.stringify(matches)) + '</p>';
          } else {
            out.innerHTML = '<p class="inv-empty">No owner overlap in top sellers (or data unavailable).</p>';
          }
        });
      })
      .catch(function () {
        if (out) out.innerHTML = '<p class="inv-banner">Owner check failed.</p>';
      });
  }

  function runAsk(netuid, question) {
    var out = document.getElementById('inv-sellers-out');
    var n = netuid != null ? Number(netuid) : Number(focusNetuid());
    if (out) out.innerHTML = '<p class="inv-loading">Asking investigation desk…</p>';
    return fetch('/api/investigate/ask', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify({ question: question, netuid: n }),
    })
      .then(function (r) { return r.json(); })
      .then(function (d) { renderAskResult(d, out); })
      .catch(function () {
        if (out) out.innerHTML = '<p class="inv-banner">Investigation ask unavailable.</p>';
      });
  }

  document.querySelectorAll('.inv-preset').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var action = btn.getAttribute('data-action') || 'chat';
      var n = focusNetuid();
      var nm = focusName();
      if (action === 'sellers') {
        runSellers(n);
        return;
      }
      if (action === 'owner-check') {
        runOwnerCheck(n);
        return;
      }
      if (action === 'ask') {
        var q = (btn.getAttribute('data-prompt') || 'Summarize seller risk for this subnet.')
          .replace(/\{name\}/g, nm)
          .replace(/\{netuid\}/g, String(n));
        runAsk(n, q);
        return;
      }
      if (action === 'wallet') {
        var w = (document.getElementById('inv-wallet').value || '').trim();
        if (!w) {
          var out = document.getElementById('inv-wallet-out');
          if (out) out.innerHTML = '<p class="inv-empty">Enter a wallet address first.</p>';
          return;
        }
        if (walletBtn) walletBtn.click();
        return;
      }
      var chatInput = document.getElementById('chatInput');
      var prompt = (btn.getAttribute('data-prompt') || '')
        .replace(/\{name\}/g, nm)
        .replace(/\{netuid\}/g, String(n));
      if (chatInput && prompt) {
        chatInput.value = prompt;
        chatInput.focus();
        var drawer = document.getElementById('market-drawer');
        if (drawer && !drawer.open) drawer.setAttribute('open', 'open');
      }
    });
  });

  document.addEventListener('living-focus:change', function () {
    var inp = document.getElementById('inv-netuid');
    if (inp) inp.value = String(focusNetuid());
    document.querySelectorAll('.inv-preset[data-action="sellers"]').forEach(function (btn) {
      btn.textContent = 'Sellers: ' + focusName();
    });
  });

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

  window.InvestigationPanel = { runSellers: runSellers, focusNetuid: focusNetuid, runOwnerCheck: runOwnerCheck, runAsk: runAsk };
})();
