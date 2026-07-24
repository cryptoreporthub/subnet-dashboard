/** Corner strip — Bittensor subnet integrations (SN22/50/64/118). */
(function () {
  'use strict';

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c];
    });
  }

  function renderRow(row) {
    var status = row.status || 'offline';
    var label = status === 'connected' ? 'Connected' : status === 'reachable' ? 'Reachable' : 'Offline';
    var chip =
      '<span class="subnet-int-chip subnet-int-chip--' +
      esc(status) +
      '" title="' +
      esc(row.role || '') +
      ' — ' +
      esc(row.detail || '') +
      '">' +
      '<span class="subnet-int-dot" aria-hidden="true"></span>' +
      '<span class="subnet-int-label">SN' +
      esc(row.netuid) +
      ' · ' +
      esc(row.name) +
      '</span>' +
      '<span class="subnet-int-state">' +
      esc(label) +
      '</span>' +
      '</span>';
    return chip;
  }

  function render(payload) {
    var root = document.getElementById('subnetIntegrationsCorner');
    if (!root) return;
    var rows = (payload && payload.integrations) || [];
    if (!rows.length) {
      root.hidden = true;
      return;
    }
    root.hidden = false;
    var connected = payload.connected_count != null ? payload.connected_count : 0;
    var target = payload.target_minimum != null ? payload.target_minimum : 3;
    var summary =
      connected >= target
        ? connected + ' subnets connected'
        : connected + ' / ' + target + ' connected';
    root.innerHTML =
      '<div class="subnet-int-inner" role="list" aria-label="Bittensor subnet integrations">' +
      '<span class="subnet-int-heading">Built on Bittensor</span>' +
      rows.map(renderRow).join('') +
      renderCandidates(payload.candidates) +
      '<span class="subnet-int-summary" title="Launch target: at least ' +
      esc(target) +
      ' live subnet integrations">' +
      esc(summary) +
      '</span>' +
      '</div>';
  }

  function renderCandidates(candidates) {
    if (!candidates || !candidates.length) return '';
    var top = candidates.slice(0, 4);
    var more = candidates.length - top.length;
    var chips = top
      .map(function (c) {
        return (
          '<span class="subnet-int-chip subnet-int-chip--candidate" title="' +
          esc(c.description || c.category || '') +
          ' · TaonSquare catalog">' +
          '<span class="subnet-int-dot" aria-hidden="true"></span>' +
          '<span class="subnet-int-label">SN' +
          esc(c.netuid) +
          ' · ' +
          esc(c.name) +
          '</span>' +
          '<span class="subnet-int-state">Next</span>' +
          '</span>'
        );
      })
      .join('');
    var tail =
      more > 0
        ? '<span class="subnet-int-more">+' +
          esc(more) +
          ' more via TaonSquare</span>'
        : '';
    return (
      '<span class="subnet-int-subheading">Could connect next</span>' + chips + tail
    );
  }

  function poll() {
    fetch('/api/subnet-integrations', { headers: { Accept: 'application/json' } })
      .then(function (r) {
        if (!r.ok) throw new Error(String(r.status));
        return r.json();
      })
      .then(render)
      .catch(function () {
        var root = document.getElementById('subnetIntegrationsCorner');
        if (root) root.hidden = true;
      });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', poll);
  } else {
    poll();
  }
  document.addEventListener('visibilitychange', function () {
    if (document.visibilityState === 'visible') poll();
  });
  setInterval(function () {
    if (document.visibilityState !== 'hidden') poll();
  }, 180000);
})();
