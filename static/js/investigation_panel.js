/* §27-3b — On-chain investigation: tables + focus-coupled presets */
(function () {
  'use strict';

  var sellersBtn = document.getElementById('inv-sellers-btn');
  var walletBtn = document.getElementById('inv-wallet-btn');
  var boardsEl = document.getElementById('whale-leaderboards');
  var whaleSummaryEl = document.getElementById('inv-whale-summary');
  var ruggerStripEl = document.getElementById('inv-rugger-strip');
  var flowStripEl = document.getElementById('inv-flow-strip');
  var signalsLoaded = false;
  if (!sellersBtn && !boardsEl && !whaleSummaryEl) return;

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
    return fetch('/api/investigate/subnet/' + encodeURIComponent(n) + '/owner-check')
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (!out) return;
        if (d.error || d.status === 'error' || d.status === 'unavailable') {
          out.innerHTML = '<p class="inv-banner">' + esc(d.message || d.error || 'Owner check unavailable.') + '</p>';
          return;
        }
        var matches = d.owner_matches || [];
        var suspects = d.suspects_among_sellers || [];
        if (matches.length) {
          out.innerHTML = '<p class="inv-banner">Owner match among sellers: ' + esc(matches.join(', ')) + '</p>';
        } else if (suspects.length) {
          out.innerHTML = '<p class="inv-banner">Suspect wallets among sellers: ' + esc(suspects.join(', ')) + '</p>';
        } else if (d.owner) {
          out.innerHTML = '<p class="inv-empty">Owner ' + esc(String(d.owner).slice(0, 16)) + '… not in top sellers.</p>';
        } else {
          out.innerHTML = '<p class="inv-empty">No owner overlap in top sellers (or data unavailable).</p>';
        }
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
    signalsLoaded = false;
    if (ruggerStripEl) loadSignalStrips();
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

  function renderWhaleSummary(summary, alerts) {
    if (!whaleSummaryEl) return;
    var body = whaleSummaryEl.querySelector('.investigation-signal-card__body');
    if (!body) body = whaleSummaryEl;
    if (!summary || summary.status !== 'success') {
      body.innerHTML = '<p class="inv-empty">Whale summary unavailable.</p>';
      return;
    }
    if (!summary.data_available) {
      var lever = summary.reason === 'no_events'
        ? 'Ledger empty — set <code>TAOSTATS_API_KEY</code> and run a whale scan.'
        : esc(summary.reason || 'no whale events yet');
      body.innerHTML = '<p class="inv-empty">' + lever + '</p>';
      return;
    }
    var stats = summary.stats || {};
    var alertCount = (alerts && alerts.total) || 0;
    var rugAlerts = (alerts && alerts.rugger_alerts) || [];
    var html =
      '<p><strong>' + esc(String(stats.total_events || 0)) + '</strong> events · ' +
      esc(String(stats.total_wallets_tracked || 0)) + ' wallets tracked</p>';
    if (alertCount) {
      html += '<p class="inv-alert-count">' + alertCount + ' active alert' + (alertCount === 1 ? '' : 's') + '</p>';
      if (rugAlerts.length) {
        html += '<ul class="inv-alert-list">';
        rugAlerts.slice(0, 3).forEach(function (a) {
          html += '<li>SN' + esc(a.netuid) + ' · exit ~' + esc(a.estimated_exit_in_hours) + 'h</li>';
        });
        html += '</ul>';
      }
    } else {
      html += '<p class="inv-muted">No active whale alerts.</p>';
    }
    body.innerHTML = html;
  }

  function renderRuggerSummary(summary) {
    if (!ruggerStripEl) return;
    var body = ruggerStripEl.querySelector('.investigation-signal-card__body');
    if (!body) body = ruggerStripEl;
    if (!summary || summary.status !== 'success') {
      body.innerHTML = '<p class="inv-empty">Rugger summary unavailable.</p>';
      return;
    }
    if (!summary.data_available) {
      body.innerHTML = '<p class="inv-empty">No rugger events — same ledger as whales; ingest via TaoStats scan.</p>';
      return;
    }
    var stats = summary.stats || {};
    var count = stats.rugger_count || 0;
    var html =
      '<p><strong>' + esc(String(count)) + '</strong> ruggers flagged · ' +
      esc(String(stats.total_flips || 0)) + ' flips tracked</p>';
    var focus = focusNetuid();
    fetch('/api/ruggers/subnet/' + encodeURIComponent(focus))
      .then(function (r) { return r.json(); })
      .then(function (risk) {
        if (risk && risk.risk_level) {
          html += '<p class="inv-rug-focus">Focus SN' + esc(focus) + ': <strong>' + esc(risk.risk_level) + '</strong>';
          if (risk.summary || risk.reason) html += ' · ' + esc(risk.summary || risk.reason);
          html += '</p>';
        }
        body.innerHTML = html;
      })
      .catch(function () {
        body.innerHTML = html;
      });
  }

  function renderFlowSignals(payload) {
    if (!flowStripEl) return;
    var body = flowStripEl.querySelector('.investigation-signal-card__body');
    if (!body) body = flowStripEl;
    if (!payload || payload.status !== 'success') {
      body.innerHTML = '<p class="inv-empty">Flow signals unavailable.</p>';
      return;
    }
    if (!payload.data_available) {
      body.innerHTML = '<p class="inv-empty">No flow events — run a whale scan or ingest delegation events.</p>';
      return;
    }
    var summary = payload.summary || {};
    var signals = (payload.signals || []).filter(function (s) {
      return s.kind === 'flow_flip' || s.kind === 'volume_surge';
    });
    var html =
      '<p><strong>' + esc(String(summary.flips || 0)) + '</strong> flips · ' +
      esc(String(summary.surges || 0)) + ' surges · net ' +
      esc(String(summary.total_net_flow_tao != null ? summary.total_net_flow_tao : '0')) + 'τ</p>';
    if (!signals.length) {
      html += '<p class="inv-muted">No flips or surges in the last ' + esc(String(payload.hours || 24)) + 'h.</p>';
      body.innerHTML = html;
      return;
    }
    html += '<ul class="inv-flow-list">';
    signals.slice(0, 4).forEach(function (s) {
      var dir = s.flip_direction === 'accumulation' ? 'flow-green' : 'flow-red';
      var name = s.subnet_name ? esc(s.subnet_name) : 'SN' + esc(s.netuid);
      var rug = s.avoid_follow ? ' · rugger' : '';
      html += '<li class="' + dir + '"><a href="/subnet/' + esc(s.netuid) + '">' + name + '</a> · ' +
        esc(s.label || s.kind) + rug + '</li>';
    });
    html += '</ul>';
    body.innerHTML = html;
  }

  function loadSignalStrips() {
    if (signalsLoaded) return Promise.resolve();
    signalsLoaded = true;
    return Promise.all([
      fetch('/api/whales/summary').then(function (r) { return r.json(); }).catch(function () { return null; }),
      fetch('/api/whales/alerts').then(function (r) { return r.json(); }).catch(function () { return null; }),
      fetch('/api/ruggers/summary').then(function (r) { return r.json(); }).catch(function () { return null; }),
      fetch('/api/whales/flow-signals?limit=12').then(function (r) { return r.json(); }).catch(function () { return null; }),
    ]).then(function (res) {
      renderWhaleSummary(res[0], res[1]);
      renderRuggerSummary(res[2]);
      renderFlowSignals(res[3]);
    });
  }

  function onMarketDrawerOpen() {
    loadSignalStrips().then(function () {
      if (sellersBtn && document.getElementById('inv-sellers-out')) {
        var out = document.getElementById('inv-sellers-out');
        if (out && (out.textContent === '—' || out.querySelector('.inv-loading'))) {
          runSellers(focusNetuid());
        }
      }
    });
  }

  var marketDrawer = document.getElementById('market-drawer');
  if (marketDrawer) {
    marketDrawer.addEventListener('toggle', function () {
      if (marketDrawer.open) onMarketDrawerOpen();
    });
    if (marketDrawer.open) onMarketDrawerOpen();
  } else {
    loadSignalStrips();
  }
  function parseWalletParam() {
    try {
      var params = new URLSearchParams(window.location.search);
      var w = (params.get('wallet') || '').trim();
      return w || null;
    } catch (e) {
      return null;
    }
  }

  function bootstrapWalletFromUrl() {
    var wallet = parseWalletParam();
    if (!wallet) return;
    var inv = document.getElementById('inv-wallet');
    if (inv) inv.value = wallet;
    var drawer = document.getElementById('market-drawer');
    if (drawer && !drawer.open) drawer.setAttribute('open', 'open');
    var section = document.getElementById('section-investigation');
    if (section) section.scrollIntoView({ behavior: 'smooth', block: 'start' });
    if (walletBtn) walletBtn.click();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', bootstrapWalletFromUrl);
  } else {
    bootstrapWalletFromUrl();
  }
})();
