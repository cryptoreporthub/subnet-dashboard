// Judge Council popup panel with live data
(function() {
  'use strict';

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c];
    });
  }

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

  function togglePanel() {
    if (modal) { modal.remove(); modal = null; return; }
    modal = document.createElement('div');
    modal.id = 'jc-modal';
    modal.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.7);z-index:99998;display:flex;align-items:center;justify-content:center;padding:20px;';
    modal.onclick = function(e) { if (e.target === modal) { modal.remove(); modal = null; } };

    var box = document.createElement('div');
    box.style.cssText = 'background:#1a1a2e;border:1px solid #c99a4b;border-radius:16px;max-width:900px;width:100%;max-height:85vh;overflow-y:auto;padding:24px;font-family:system-ui,sans-serif;color:#e0e0e0;';
    box.innerHTML = `
<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:16px;">
  <h2 style="margin:0;font-size:18px;color:#c99a4b;">\u2696\ufe0f Judge Council</h2>
  <button id="jc-close" style="background:none;border:none;color:#888;font-size:22px;cursor:pointer;line-height:1;">\u00d7</button>
</div>
<div id="jc-stats" style="font-size:13px;color:#888;margin-bottom:12px;"></div>
<div id="jc-content" style="padding:40px;text-align:center;color:#888;">
  Loading judge scores...
</div>
`;
    modal.appendChild(box);
    document.body.appendChild(modal);

    document.getElementById('jc-close').onclick = function() { modal.remove(); modal = null; };

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
        var stats = document.getElementById('jc-stats');
        if (!el) return;

        var judges = data.judges || [];
        if (!judges.length) {
          el.innerHTML = `<p style="text-align:center;color:#888;">No judge data available yet. The background scheduler refreshes every 5 minutes.</p>`;
          stats.innerHTML = '0 subnets scored';
          return;
        }

        // Update stats
        stats.innerHTML = '<strong>' + judges.length + '</strong> subnets scored \u00b7 3 judges (Oracle, Echo, Pulse)' +
          (data.source ? ' \u00b7 source: ' + esc(data.source) : '');

        // Build search box
        var html = `<div style="margin-bottom:12px;">
  <input id="jc-search" type="text" placeholder="Search subnets\u2026"
    style="width:100%;padding:8px 12px;background:#0d0d1a;border:1px solid #333;border-radius:8px;color:#e0e0e0;font-size:14px;box-sizing:border-box;">
</div>`;

        // Build table
        html += `<div style="overflow-x:auto;"><table style="width:100%;border-collapse:collapse;font-size:13px;">
<thead><tr style="color:#c99a4b;border-bottom:1px solid #333;">
  <th style="padding:8px 4px;text-align:right;">#</th>
  <th style="padding:8px 8px;text-align:left;">Subnet</th>
  <th style="padding:8px 4px;text-align:right;">Oracle</th>
  <th style="padding:8px 4px;text-align:right;">Echo</th>
  <th style="padding:8px 4px;text-align:right;">Pulse</th>
  <th style="padding:8px 4px;text-align:right;">Consensus</th>
  <th style="padding:8px 8px;text-align:left;">Verdict</th>
</tr></thead><tbody>`;

        judges.forEach(function(j, idx) {
          var verdictColor = j.consensus && j.consensus.verdict === 'bullish' ? '#4caf50' : j.consensus && j.consensus.verdict === 'bearish' ? '#f44336' : '#888';
          var score = j.consensus ? j.consensus.score.toFixed(3) : 'N/A';
          var verdict = j.consensus ? esc(String(j.consensus.verdict)) : 'N/A';
          var agreement = j.consensus ? (j.consensus.agreement * 100).toFixed(0) + '%' : 'N/A';
          var oracleDegr = j.oracle && j.oracle.degraded ? ' \u26a0' : '';
          var echoDegr = j.echo && j.echo.degraded ? ' \u26a0' : '';
          var pulseDegr = j.pulse && j.pulse.degraded ? ' \u26a0' : '';
          var searchKey = (j.name || '') + ' sn' + j.netuid;
          html += `<tr class="jc-row" data-search="${searchKey.toLowerCase()}" style="border-bottom:1px solid #1e1e2e;">
  <td style="padding:8px 4px;text-align:right;color:#666;">${idx + 1}</td>
  <td style="padding:8px 8px;">${esc(j.name || ('SN' + j.netuid))} <span style="color:#666;font-size:11px;">SN${j.netuid}</span></td>
  <td style="padding:8px 4px;text-align:right;">${j.oracle ? j.oracle.score.toFixed(3) : '-'}${oracleDegr}</td>
  <td style="padding:8px 4px;text-align:right;">${j.echo ? j.echo.score.toFixed(3) : '-'}${echoDegr}</td>
  <td style="padding:8px 4px;text-align:right;">${j.pulse ? j.pulse.score.toFixed(3) : '-'}${pulseDegr}</td>
  <td style="padding:8px 4px;text-align:right;">${score} <span style="color:#666;font-size:11px;">${agreement}</span></td>
  <td style="padding:8px 8px;color:${verdictColor};">${verdict}</td>
</tr>`;
        });
        html += '</tbody></table></div>';

        el.innerHTML = html;
        el.style.padding = '0';

        // Wire up search
        var searchInput = document.getElementById('jc-search');
        if (searchInput) {
          searchInput.oninput = function() {
            var q = searchInput.value.toLowerCase();
            var rows = document.querySelectorAll('.jc-row');
            var visible = 0;
            rows.forEach(function(r) {
              var match = r.getAttribute('data-search').indexOf(q) !== -1;
              r.style.display = match ? '' : 'none';
              if (match) visible++;
            });
          };
        }
      })
      .catch(function(err) {
        var el = document.getElementById('jc-content');
        if (el) el.innerHTML = `<p style="color:#f44336;">Failed to load judge data: ${esc(err.message)}</p>
<p style="color:#888;font-size:13px;">The /api/judges endpoint may still be starting up. Try again in a moment.</p>`;
      });
  }
})();
