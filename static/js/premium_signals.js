/* Phase L — live signals + alerts via /ws/signals (SSR snapshot fallback). */
(function () {
  'use strict';

  var summaryRoot = document.getElementById('signal-summary-root');
  var signalsRoot = document.getElementById('signals-feed-root');
  var alertsRoot = document.getElementById('alerts-feed-root');
  var countMeta = document.getElementById('signals-count-meta');
  var wsStatus = document.getElementById('signals-ws-status');
  if (!summaryRoot && !signalsRoot && !alertsRoot) return;

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c];
    });
  }

  function signalBadge(type) {
    var t = String(type || 'neutral').toLowerCase();
    if (t === 'buy') return 'badge-buy';
    if (t === 'sell') return 'badge-sell';
    return 'badge-watch';
  }

  function severityBadge(sev) {
    var s = String(sev || 'info').toLowerCase();
    if (s === 'critical') return 'badge-sell';
    if (s === 'warning') return 'badge-hot';
    return 'badge-watch';
  }

  function summarizeSignals(signals) {
    var buy = 0;
    var sell = 0;
    var neutral = 0;
    var confSum = 0;
    (signals || []).forEach(function (sig) {
      var t = String(sig.signal_type || 'neutral').toLowerCase();
      if (t === 'buy') buy += 1;
      else if (t === 'sell') sell += 1;
      else neutral += 1;
      confSum += parseFloat(sig.confidence) || 0;
    });
    var n = (signals || []).length;
    return {
      total_subnets: n,
      buy_count: buy,
      sell_count: sell,
      neutral_count: neutral,
      buy_sell_ratio: sell ? Math.round((buy / sell) * 10000) / 10000 : buy,
      avg_confidence: n ? confSum / n : 0,
    };
  }

  function renderSummary(sum) {
    if (!summaryRoot || !sum) return;
    summaryRoot.innerHTML =
      '<div class="kpi card"><div class="lbl">Tracked</div><div class="val">' + esc(sum.total_subnets) +
      '</div><div class="sub">subnets with signals</div></div>' +
      '<div class="kpi card"><div class="lbl">Buy</div><div class="val pos">' + esc(sum.buy_count) +
      '</div><div class="sub">bullish posture</div></div>' +
      '<div class="kpi card"><div class="lbl">Sell</div><div class="val neg">' + esc(sum.sell_count) +
      '</div><div class="sub">bearish posture</div></div>' +
      '<div class="kpi card"><div class="lbl">Neutral</div><div class="val">' + esc(sum.neutral_count) +
      '</div><div class="sub">ratio ' + esc(sum.buy_sell_ratio) + '</div></div>' +
      '<div class="kpi card"><div class="lbl">Avg conf</div><div class="val accent-bright">' +
      (sum.avg_confidence * 100).toFixed(1) + '%</div><div class="sub">council confidence</div></div>';
    summaryRoot.className = 'kpi-strip';
  }

  function renderSignals(signals) {
    if (!signalsRoot) return;
    var rows = (signals || []).slice().sort(function (a, b) {
      return (parseFloat(b.confidence) || 0) - (parseFloat(a.confidence) || 0);
    }).slice(0, 12);
    if (!rows.length) {
      signalsRoot.innerHTML = '<p class="empty">Signal pipeline warming up — council scores populate after subnet registry loads.</p>';
      if (countMeta) countMeta.textContent = '0 subnets';
      return;
    }
    if (countMeta) countMeta.textContent = (signals || []).length + ' subnets';
    var body = rows.map(function (sig) {
      var st = String(sig.signal_type || 'neutral').toLowerCase();
      var conf = ((parseFloat(sig.confidence) || 0) * 100).toFixed(1);
      var evidence = String(sig.evidence || '—');
      if (evidence.length > 80) evidence = evidence.slice(0, 77) + '…';
      return '<tr><td class="text-primary">' + esc(sig.name || ('SN' + sig.subnet_id)) +
        ' <span class="pick-meta">SN' + esc(sig.subnet_id) + '</span></td>' +
        '<td><span class="badge ' + signalBadge(st) + '">' + esc(st.toUpperCase()) + '</span></td>' +
        '<td>' + conf + '%</td><td>' + esc(sig.source_expert || '—') + '</td>' +
        '<td class="pick-meta">' + esc(evidence) + '</td></tr>';
    }).join('');
    signalsRoot.innerHTML = '<table class="tbl"><thead><tr><th>Subnet</th><th>Type</th><th>Conf</th><th>Expert</th><th>Evidence</th></tr></thead><tbody>' +
      body + '</tbody></table>';
  }

  function renderAlerts(alerts) {
    if (!alertsRoot) return;
    var rows = (alerts || []).slice(0, 12);
    if (!rows.length) {
      alertsRoot.innerHTML = '<div class="card card-muted"><p class="empty">No active alerts — threshold breaches and signal changes appear here when detected.</p></div>';
      return;
    }
    alertsRoot.innerHTML = rows.map(function (alert) {
      var sev = String(alert.severity || 'info').toLowerCase();
      var meta = esc(alert.timestamp || '');
      if (alert.subnet_id != null) meta += ' · SN' + esc(alert.subnet_id);
      return '<article class="pick-card card"><div class="pick-meta">' + meta + '</div>' +
        '<div class="pick-name">' + esc(alert.message || alert.alert_type || 'alert') + '</div>' +
        '<div class="tags" style="margin-top:8px;">' +
        '<span class="badge ' + severityBadge(sev) + '">' + esc(sev.toUpperCase()) + '</span>' +
        '<span class="badge badge-watch">' + esc(alert.alert_type || 'system') + '</span></div></article>';
    }).join('');
    alertsRoot.className = 'picks';
  }

  function applyPayload(signals, alerts) {
    if (signals) {
      renderSummary(summarizeSignals(signals));
      renderSignals(signals);
    }
    if (alerts) renderAlerts(alerts);
  }

  function setWsStatus(label) {
    if (wsStatus) wsStatus.textContent = label;
  }

  function connectWs() {
    var proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    var url = proto + '//' + window.location.host + '/ws/signals';
    var ws;
    try {
      ws = new WebSocket(url);
    } catch (e) {
      setWsStatus('snapshot (ws unavailable)');
      return;
    }
    ws.onopen = function () {
      setWsStatus('live ws');
    };
    ws.onmessage = function (ev) {
      var msg;
      try {
        msg = JSON.parse(ev.data);
      } catch (e) {
        return;
      }
      var type = msg.type;
      var data = msg.data || {};
      if (type === 'connected') {
        applyPayload(data.signals, data.alerts);
      } else if (type === 'signals' && data.signals) {
        applyPayload(data.signals, null);
      } else if (type === 'alerts' && data.alerts) {
        renderAlerts(data.alerts);
      }
    };
    ws.onclose = function () {
      setWsStatus('snapshot (ws closed)');
    };
    ws.onerror = function () {
      setWsStatus('snapshot (ws error)');
    };
    window.setInterval(function () {
      if (ws.readyState === WebSocket.OPEN) ws.send('ping');
    }, 45000);
  }

  connectWs();
})();
