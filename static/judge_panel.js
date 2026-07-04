// Judge Council popup panel with live data — shows ALL scored subnets
(function() {
  'use strict';

  var btn = document.createElement('div');
  btn.id = 'jc-trigger';
  btn.innerHTML = '\u2696\ufe0f';
  btn.style.cssText = 'position:fixed;bottom:20px;right:20px;width:56px;height:56px;border-radius:50%;background:#c99a4b;color:#1a1a2e;display:flex;align-items:center;justify-content:center;font-size:24px;cursor:pointer;z-index:99999;box-shadow:0 4px 20px rgba(0,0,0,0.5);transition:transform 0.2s;';
  btn.onmouseover = function() { btn.style.transform = 'scale(1.1)'; };
  btn.onmouseout = function() { btn.style.transform = 'scale(1)'; };
  btn.onclick = function() { togglePanel(); };
  document.body.appendChild(btn);

  var modal = null;

  function togglePanel() {
    if (modal) { modal.remove(); modal = null; return; }
    modal = document.createElement('div');
    modal.id = 'jc-modal';
    modal.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.7);z-index:99998;display:flex;align-items:center;justify-content:center;padding:20px;';
    modal.onclick = function(e) { if (e.target === modal) { modal.remove(); modal = null; } };

    var box = document.createElement('div');
    box.style.cssText = 'background:#1a1a2e;border:1px solid #c99a4b;border-radius:16px;max-width:900px;width:100%;max-height:85vh;overflow-y:auto;padding:24px;font-family:system-ui,sans-serif;color:#e0e0e0;';
    box.innerHTML = '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">' +
      '<h2 style="margin:0;font-size:20px;color:#c99a4b;">\u2696\ufe0f Judge Council</h2>' +
      '<button id="jc-close" style="background:none;border:none;color:#888;font-size:24px;cursor:pointer;">\u00d7</button></div>' +
      '<div id="jc-meta" style="color:#666;font-size:12px;margin-bottom:12px;"></div>' +
      '<input id="jc-search" type="text" placeholder="Filter by name or SN..." style="width:100%;padding:8px 12px;margin-bottom:12px;background:#0d0d1a;border:1px solid #333;border-radius:8px;color:#e0e0e0;font-size:13px;box-sizing:border-box;">' +
      '<div id="jc-content" style="color:#aaa;"><p>Loading judge scores...</p></div>';
    modal.appendChild(box);
    document.body.appendChild(modal);

    document.getElementById('jc-close').onclick = function() { modal.remove(); modal = null; };
    document.getElementById('jc-search').addEventListener('input', function(e) {
      var term = e.target.value.toLowerCase().trim();
      var rows = document.querySelectorAll('#jc-tbody tr');
      rows.forEach(function(row) {
        var text = row.textContent.toLowerCase();
        row.style.display = term === '' || text.indexOf(term) !== -1 ? '' : 'none';
      });
    });

    loadData();
  }

  function loadData() {
    fetch('/api/judges')
      .then(function(r) {
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.json();
      })
      .then(function(data) {
        var el = document.getElementById('jc-content');
        var meta = document.getElementById('jc-meta');
        if (!el) return;

        var judges = data.judges || [];
        if (!judges.length) {
          el.innerHTML = '<p style="color:#888;">No judge data available yet. The background scheduler refreshes every 5 minutes.</p>';
          return;
        }

        // Update meta
        meta.textContent = judges.length + ' subnets scored \u00b7 3 judges (Oracle, Echo, Pulse)' +
          (data.source ? ' \u00b7 source: ' + data.source : '');

        var html = '<table style="width:100%;border-collapse:collapse;font-size:12px;">' +
          '<thead><tr style="border-bottom:1px solid #333;position:sticky;top:0;background:#1a1a2e;">' +
          '<th style="text-align:left;padding:6px;color:#c99a4b;">Subnet</th>' +
          '<th style="padding:6px;color:#c99a4b;">Oracle</th>' +
          '<th style="padding:6px;color:#c99a4b;">Echo</th>' +
          '<th style="padding:6px;color:#c99a4b;">Pulse</th>' +
          '<th style="padding:6px;color:#c99a4b;">Consensus</th>' +
          '<th style="padding:6px;color:#c99a4b;">Verdict</th>' +
          '</tr></thead><tbody id="jc-tbody">';

        // Show ALL subnets, not just top 30
        judges.forEach(function(j) {
          var verdictColor = j.consensus && j.consensus.verdict === 'bullish' ? '#4caf50' :
            j.consensus && j.consensus.verdict === 'bearish' ? '#f44336' : '#888';
          var score = j.consensus ? j.consensus.score.toFixed(2) : 'N/A';
          var verdict = j.consensus ? j.consensus.verdict : 'N/A';
          var agreement = j.consensus ? (j.consensus.agreement * 100).toFixed(0) + '%' : 'N/A';

          html += '<tr style="border-bottom:1px solid #222;">' +
            '<td style="padding:6px;">' + (j.name || 'SN' + j.netuid) + ' <span style="color:#666;">SN' + j.netuid + '</span></td>' +
            '<td style="padding:6px;text-align:center;">' + (j.oracle ? j.oracle.score.toFixed(2) : '-') + (j.oracle && j.oracle.degraded ? ' \u26a0' : '') + '</td>' +
            '<td style="padding:6px;text-align:center;">' + (j.echo ? j.echo.score.toFixed(2) : '-') + (j.echo && j.echo.degraded ? ' \u26a0' : '') + '</td>' +
            '<td style="padding:6px;text-align:center;">' + (j.pulse ? j.pulse.score.toFixed(2) : '-') + (j.pulse && j.pulse.degraded ? ' \u26a0' : '') + '</td>' +
            '<td style="padding:6px;text-align:center;color:#c99a4b;">' + score + ' <span style="color:#666;font-size:10px;">' + agreement + '</span></td>' +
            '<td style="padding:6px;text-align:center;color:' + verdictColor + ';">' + verdict + '</td>' +
            '</tr>';
        });

        html += '</tbody></table>';
        el.innerHTML = html;
        el.style.padding = '0';
      })
      .catch(function(err) {
        var el = document.getElementById('jc-content');
        if (el) el.innerHTML = '<p style="color:#f44336;">Failed to load judge data: ' + err.message + '</p>' +
          '<p style="color:#888;font-size:12px;">The /api/judges endpoint may still be starting up. Try again in a moment.</p>';
      });
  }
})();
