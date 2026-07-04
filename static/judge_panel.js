// Judge Council popup panel with live data
(function() {
  // Create floating button
  var btn = document.createElement('div');
  btn.id = 'jc-trigger';
  btn.innerHTML = '\u2696\ufe0f';
  btn.style.cssText = 'position:fixed;bottom:20px;right:20px;width:56px;height:56px;border-radius:50%;background:#c99a4b;color:#1a1a2e;display:flex;align-items:center;justify-content:center;font-size:24px;cursor:pointer;z-index:99999;box-shadow:0 4px 20px rgba(0,0,0,0.5);transition:transform 0.2s;';
  btn.onmouseover = function() { btn.style.transform = 'scale(1.1)'; };
  btn.onmouseout = function() { btn.style.transform = 'scale(1)'; };
  btn.onclick = function() { togglePanel(); };
  document.body.appendChild(btn);

  var modal = null;
  var loaded = false;

  function togglePanel() {
    if (modal) { modal.remove(); modal = null; return; }
    modal = document.createElement('div');
    modal.id = 'jc-modal';
    modal.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.7);z-index:99998;display:flex;align-items:center;justify-content:center;padding:20px;';
    modal.onclick = function(e) { if (e.target === modal) { modal.remove(); modal = null; } };

    var box = document.createElement('div');
    box.style.cssText = 'background:#1a1a2e;border:1px solid #c99a4b;border-radius:16px;max-width:800px;width:100%;max-height:85vh;overflow-y:auto;padding:24px;font-family:system-ui,sans-serif;color:#e0e0e0;';
    box.innerHTML = '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;">' +
      '<div style="display:flex;align-items:center;gap:10px;"><span style="font-size:28px;">\u2696\ufe0f</span><span style="font-size:20px;font-weight:bold;color:#c99a4b;">Judge Council</span></div>' +
      '<button id="jc-close" style="background:none;border:none;color:#888;font-size:24px;cursor:pointer;">\u00d7</button></div>' +
      '<p style="color:#888;font-size:13px;margin:0 0 16px;">AI judges evaluating subnet performance</p>' +
      '<div id="jc-content" style="display:flex;align-items:center;justify-content:center;padding:40px;color:#888;">Loading judge scores...</div>';
    modal.appendChild(box);
    document.body.appendChild(modal);

    document.getElementById('jc-close').onclick = function() { modal.remove(); modal = null; };

    if (!loaded) { loadData(); }
  }

  function loadData() {
    fetch('/api/judges').then(function(r) { return r.json(); }).then(function(data) {
      var el = document.getElementById('jc-content');
      if (!el) return;
      if (!data.success && data.judges && data.judges.length === 0) {
        el.innerHTML = '<p style="color:#888;">No judge data available yet.</p>';
        return;
      }
      var judges = data.judges || [];
      var html = '<table style="width:100%;border-collapse:collapse;font-size:13px;">' +
        '<thead><tr style="border-bottom:2px solid #c99a4b;text-align:left;">' +
        '<th style="padding:8px;color:#c99a4b;">Subnet</th>' +
        '<th style="padding:8px;color:#c99a4b;text-align:center;">Oracle</th>' +
        '<th style="padding:8px;color:#c99a4b;text-align:center;">Echo</th>' +
        '<th style="padding:8px;color:#c99a4b;text-align:center;">Pulse</th>' +
        '<th style="padding:8px;color:#c99a4b;text-align:center;">Consensus</th>' +
        '<th style="padding:8px;color:#c99a4b;text-align:center;">Verdict</th>' +
        '</tr></thead><tbody>';
      judges.forEach(function(j) {
        var verdictColor = j.consensus && j.consensus.verdict === 'bullish' ? '#4caf50' : j.consensus && j.consensus.verdict === 'bearish' ? '#f44336' : '#888';
        var score = j.consensus ? j.consensus.score.toFixed(2) : 'N/A';
        var verdict = j.consensus ? j.consensus.verdict : 'N/A';
        var agreement = j.consensus ? (j.consensus.agreement * 100).toFixed(0) + '%' : 'N/A';
        html += '<tr style="border-bottom:1px solid #333;">' +
          '<td style="padding:8px;"><span style="color:#c99a4b;font-weight:bold;">' + (j.name || 'SN' + j.netuid) + '</span><br><span style="color:#666;font-size:11px;">SN' + j.netuid + '</span></td>' +
          '<td style="padding:8px;text-align:center;' + (j.oracle && j.oracle.degraded ? 'color:#667;' : 'color:#e0e0e0;') + '">' + (j.oracle ? j.oracle.score.toFixed(2) : '-') + '</td>' +
          '<td style="padding:8px;text-align:center;' + (j.echo && j.echo.degraded ? 'color:#667;' : 'color:#e0e0e0;') + '">' + (j.echo ? j.echo.score.toFixed(2) : '-') + '</td>' +
          '<td style="padding:8px;text-align:center;' + (j.pulse && j.pulse.degraded ? 'color:#667;' : 'color:#e0e0e0;') + '">' + (j.pulse ? j.pulse.score.toFixed(2) : '-') + '</td>' +
          '<td style="padding:8px;text-align:center;font-weight:bold;color:#c99a4b;">' + score + '<br><span style="font-size:10px;color:#888;">' + agreement + ' agree</span></td>' +
          '<td style="padding:8px;text-align:center;font-weight:bold;color:' + verdictColor + ';text-transform:uppercase;font-size:11px;">' + verdict + '</td>' +
        '</tr>';
      });
      html += '</tbody></table>';
      html += '<div style="margin-top:12px;color:#555;font-size:11px;text-align:right;">' + judges.length + ' subnets scored · 3 judges (Oracle, Echo, Pulse)</div>';
      el.innerHTML = html;
      el.style.padding = '0';
      el.style.display = 'block';
      loaded = true;
    }).catch(function(err) {
      var el = document.getElementById('jc-content');
      if (el) el.innerHTML = '<p style="color:#f44336;">Failed to load judge data: ' + err.message + '</p>';
    });
  }
})();